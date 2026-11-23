"""Background job execution: analysis pipeline and clip export.

Jobs are persisted in SQLite on every state change, progress is pushed to WebSocket clients,
heavy work runs in worker threads (one heavy task at a time), and jobs that were interrupted by a
backend restart are marked failed on startup so the user can restart them safely.
"""
from __future__ import annotations

import asyncio
import re
import shutil
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

from sqlalchemy import delete, select, text
from sqlalchemy.orm import selectinload

from backend.app import clip_detector, metadata_generator, transcription, video_import as vi, video_processor as vp
from backend.app.config import settings
from backend.app.database import Base, async_session_maker, engine
from backend.app.export import ExportError, render_clip
from backend.app.models.clip import Clip
from backend.app.models.job import Job
from backend.app.models.transcript import TranscriptSegment
from backend.app.models.video import Video
from backend.app.status import ACTIVE_JOB_STATUSES, to_import_state

IMPORT_STATES = (
    "QUEUED",
    "INITIALIZING",
    "DOWNLOADING",
    "UPLOADING",
    "VALIDATING",
    "EXTRACTING_METADATA",
    "COMPLETED",
    "FAILED",
    "CANCELLED",
)

ACTIVE_STATUSES = tuple(ACTIVE_JOB_STATUSES)

active_websockets: Dict[str, List[Any]] = {}
active_url_imports: Dict[str, str] = {}  # canonical_url -> job_id
cancelled: set[str] = set()
_tasks: set[asyncio.Task] = set()
_job_locks: Dict[str, asyncio.Lock] = {}
_heavy: Optional[asyncio.Semaphore] = None
_import_sem_inst: Optional[asyncio.Semaphore] = None
_export_sem_inst: Optional[asyncio.Semaphore] = None


def _get_job_lock(job_id: str) -> asyncio.Lock:
    lock = _job_locks.get(job_id)
    if lock is None:
        lock = asyncio.Lock()
        _job_locks[job_id] = lock
    return lock


def _sem() -> asyncio.Semaphore:
    global _heavy
    if _heavy is None:
        limit = max(1, int(getattr(settings, "MAX_CONCURRENT_TRANSCRIPTIONS", 1) or 1))
        _heavy = asyncio.Semaphore(limit)
    return _heavy


def _import_sem() -> asyncio.Semaphore:
    global _import_sem_inst
    if _import_sem_inst is None:
        limit = max(1, int(getattr(settings, "MAX_CONCURRENT_IMPORTS", 1) or 1))
        _import_sem_inst = asyncio.Semaphore(limit)
    return _import_sem_inst


def _export_sem() -> asyncio.Semaphore:
    global _export_sem_inst
    if _export_sem_inst is None:
        limit = max(1, int(getattr(settings, "MAX_CONCURRENT_EXPORTS", 1) or 1))
        _export_sem_inst = asyncio.Semaphore(limit)
    return _export_sem_inst


def save_energy(video_id: str, energy: List[float]) -> None:
    p = Path(settings.TEMP_DIR) / video_id / "energy.json"
    p.parent.mkdir(parents=True, exist_ok=True)
    import json
    p.write_text(json.dumps(energy), encoding="utf-8")


def load_energy(video_id: str) -> List[float]:
    p = Path(settings.TEMP_DIR) / video_id / "energy.json"
    if not p.exists():
        return []
    import json
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return []


def spawn(coro) -> asyncio.Task:
    task = asyncio.create_task(coro)
    _tasks.add(task)
    task.add_done_callback(_tasks.discard)
    return task


running: set[str] = set()


def is_running(job_id: str) -> bool:
    return job_id in running


def get_active_url_job(url: str) -> Optional[str]:
    norm = vi.normalize_url(url)
    jid = active_url_imports.get(norm)
    if jid and jid in running:
        return jid
    active_url_imports.pop(norm, None)
    return None


def start_pipeline(job_id: str, gemini_api_key: Optional[str] = None, openai_api_key: Optional[str] = None) -> bool:
    """Queue the analysis pipeline; False if this job is already queued/running."""
    if job_id in running:
        return False
    running.add(job_id)

    async def _wrapped():
        try:
            await run_pipeline(job_id, gemini_api_key=gemini_api_key, openai_api_key=openai_api_key)
        finally:
            running.discard(job_id)

    spawn(_wrapped())
    return True


def start_url_import(job_id: str, url: str, gemini_api_key: Optional[str] = None, openai_api_key: Optional[str] = None) -> bool:
    """Queue a background URL download & metadata import job; prevents duplicate workers."""
    norm = vi.normalize_url(url)
    if job_id in running:
        return False
    existing = get_active_url_job(url)
    if existing and existing != job_id:
        return False
    running.add(job_id)
    active_url_imports[norm] = job_id

    async def _wrapped():
        try:
            await run_url_import(job_id, url.strip(), gemini_api_key=gemini_api_key, openai_api_key=openai_api_key, canonical_url=norm)
        finally:
            running.discard(job_id)
            if active_url_imports.get(norm) == job_id:
                active_url_imports.pop(norm, None)

    spawn(_wrapped())
    return True


async def shutdown_cleanup() -> None:
    """Cancel active jobs and terminate external download subprocess trees on server shutdown."""
    for jid in list(running):
        cancelled.add(jid)
    vi.terminate_all_download_processes()
    for t in list(_tasks):
        t.cancel()
    if _tasks:
        await asyncio.gather(*list(_tasks), return_exceptions=True)


async def broadcast(key: str, payload: dict) -> None:
    conns = active_websockets.get(key)
    if not conns:
        return
    dead: List[Any] = []
    for ws in list(conns):
        try:
            await ws.send_json(payload)
        except Exception:
            dead.append(ws)
    if dead:
        for ws in dead:
            if ws in conns:
                conns.remove(ws)
        if not conns:
            active_websockets.pop(key, None)


def _build_ws_payload(job: Job) -> dict:
    opts = job.settings or {}
    return {
        "job_id": job.id,
        "status": job.status,
        "import_state": opts.get("import_state", to_import_state(job.status)),
        "progress": job.progress,
        "stage": job.current_stage,
        "error": job.error_message,
        "bytes_transferred": opts.get("bytes_transferred", 0),
        "total_bytes": opts.get("total_bytes"),
        "speed_bps": opts.get("speed_bps", 0.0),
        "eta_seconds": opts.get("eta_seconds"),
        "elapsed_seconds": opts.get("elapsed_seconds", 0.0),
        "chunks_received": opts.get("chunks_received", 0),
        "total_chunks": opts.get("total_chunks", 0),
        "can_resume": bool(opts.get("can_resume", False)),
        "transcribed_seconds": opts.get("transcribed_seconds", 0.0),
        "total_audio_seconds": opts.get("total_audio_seconds", 0.0),
        "whisper_model": opts.get("whisper_model") or settings.WHISPER_MODEL or "base",
        "whisper_profile": opts.get("whisper_profile") or opts.get("transcription_profile") or settings.WHISPER_PROFILE or "balanced",
        "whisper_device": opts.get("whisper_device"),
        "realtime_factor": opts.get("realtime_factor", 0.0),
        "detected_language": getattr(job, "detected_language", None) or opts.get("detected_language"),
        "detected_language_probability": opts.get("detected_language_probability"),
    }


async def set_job(job_id: str, *, status: Optional[str] = None, progress: Optional[int] = None,
                  stage: Optional[str] = None, error: Optional[str] = None,
                  telemetry: Optional[dict] = None, **fields) -> None:
    async with _get_job_lock(job_id):
        async with async_session_maker() as s:
            job = await s.get(Job, job_id)
            if not job:
                return
            # Prevent late non-terminal ticks from overwriting a terminal cancelled/failed/completed state
            if status is not None and job.status in ("cancelled", "failed", "completed", "ready"):
                if status.lower() in ("initializing", "downloading", "uploading", "validating", "extracting_metadata"):
                    return
            if status is not None:
                job.status = status.lower()
            if progress is not None:
                job.progress = progress
            if stage is not None:
                job.current_stage = stage
            if error is not None:
                job.error_message = error
            if telemetry:
                cur_settings = dict(job.settings or {})
                cur_settings.update(telemetry)
                job.settings = cur_settings
            for k, v in fields.items():
                setattr(job, k, v)
            await s.commit()
            payload = _build_ws_payload(job)
    await broadcast(job_id, payload)


async def run_url_import(
    job_id: str,
    url: str,
    gemini_api_key: Optional[str] = None,
    openai_api_key: Optional[str] = None,
    canonical_url: Optional[str] = None,
) -> None:
    """Background worker for YouTube/Twitch URL imports using yt-dlp with progress hooks & resume support."""
    should_analyze = False
    canon = canonical_url or vi.normalize_url(url)
    async with _import_sem():
        cancelled.discard(job_id)
        async with async_session_maker() as s:
            job = (await s.execute(select(Job).where(Job.id == job_id).options(selectinload(Job.video)))).scalar_one_or_none()
            if not job or not job.video:
                return
            if job.status in ("cancelled", "CANCELLED"):
                return
            video_id = job.video.id
            opts = dict(job.settings or {})

        dest_dir = vi.storage_dir_for(video_id)
        loop = asyncio.get_running_loop()
        t_start = time.monotonic()
        last_emit = {"ws_t": 0.0, "db_t": 0.0, "stage": ""}
        emit_lock = __import__("threading").Lock()

        await set_job(
            job_id,
            status="INITIALIZING",
            progress=2,
            stage="INITIALIZING: Preparing stream download",
            error="",
            telemetry={"import_state": "INITIALIZING", "source_url": url, "elapsed_seconds": 0.0, "can_resume": True},
        )

        def on_progress(p: vi.ImportProgress) -> None:
            now = time.monotonic()
            elapsed_s = round(now - t_start, 1)
            with emit_lock:
                stage_changed = p.stage != last_emit["stage"]
                if not stage_changed and (now - last_emit["ws_t"]) < 0.25 and p.progress < 90:
                    return
                last_emit["ws_t"] = now
                persist_db = stage_changed or p.progress >= 90 or (now - last_emit["db_t"]) >= 2.0
                if persist_db:
                    last_emit["db_t"] = now
                    last_emit["stage"] = p.stage

            stage_msg = p.message or p.stage
            if p.stage == "DOWNLOADING" and p.speed_bps > 0:
                mb_s = p.speed_bps / (1024 * 1024)
                dl_mb = p.bytes_transferred / (1024 * 1024)
                if p.total_bytes:
                    tot_mb = p.total_bytes / (1024 * 1024)
                    eta_str = f", ETA {int(p.eta_seconds)}s" if p.eta_seconds is not None else ""
                    stage_msg = f"DOWNLOADING: {dl_mb:.1f}/{tot_mb:.1f} MB ({mb_s:.1f} MB/s{eta_str})"
                else:
                    stage_msg = f"DOWNLOADING: {dl_mb:.1f} MB ({mb_s:.1f} MB/s)"

            tel_data = {
                "import_state": p.stage,
                "bytes_transferred": p.bytes_transferred,
                "total_bytes": p.total_bytes,
                "speed_bps": p.speed_bps,
                "eta_seconds": p.eta_seconds,
                "elapsed_seconds": elapsed_s,
                "chunks_received": p.chunks_received,
                "total_chunks": p.total_chunks,
                "can_resume": True,
            }
            if persist_db:
                asyncio.run_coroutine_threadsafe(
                    set_job(
                        job_id,
                        status=p.stage,
                        progress=p.progress,
                        stage=stage_msg,
                        telemetry=tel_data,
                    ),
                    loop,
                )
            else:
                asyncio.run_coroutine_threadsafe(
                    broadcast(job_id, {
                        "job_id": job_id,
                        "status": p.stage.lower(),
                        "import_state": p.stage,
                        "progress": p.progress,
                        "stage": stage_msg,
                        **tel_data,
                    }),
                    loop,
                )

        try:
            path, meta, platform, title = await asyncio.to_thread(
                vi.import_external,
                url,
                dest_dir,
                progress_cb=on_progress,
                should_cancel=lambda: job_id in cancelled,
                keep_partial_on_error=True,
                job_id=job_id,
            )
            _check(job_id)

            async with async_session_maker() as s:
                video = await s.get(Video, video_id)
                if video:
                    video.filename = title
                    video.source_type = platform
                    video.original_url = url
                    video.file_path = str(path)
                    video.file_size_mb = meta.file_size_mb
                    video.duration = meta.duration
                    video.width = meta.width
                    video.height = meta.height
                    video.fps = meta.fps
                    video.is_vfr = meta.is_vfr
                    video.codec = meta.codec
                    video.audio_codec = meta.audio_codec or ""
                    video.status = "ready"
                    await s.commit()

            elapsed_total = round(time.monotonic() - t_start, 1)
            await set_job(
                job_id,
                status="COMPLETED",
                progress=100,
                stage="COMPLETED: Video imported and metadata extracted",
                last_completed_stage="import",
                telemetry={
                    "import_state": "COMPLETED",
                    "bytes_transferred": meta.file_size_bytes,
                    "total_bytes": meta.file_size_bytes,
                    "speed_bps": 0.0,
                    "eta_seconds": 0.0,
                    "elapsed_seconds": elapsed_total,
                    "can_resume": False,
                },
            )
            should_analyze = bool(opts.get("auto_analyze", False))

        except _Cancelled:
            vi._cleanup_partial_downloads(dest_dir)
            await set_job(
                job_id,
                status="CANCELLED",
                stage="CANCELLED: Import cancelled by user",
                telemetry={"import_state": "CANCELLED", "can_resume": False},
            )
            return
        except vi.ImportFailure as exc:
            if exc.status == 499 or job_id in cancelled:
                vi._cleanup_partial_downloads(dest_dir)
                await set_job(
                    job_id,
                    status="CANCELLED",
                    stage="CANCELLED: Import cancelled by user",
                    telemetry={"import_state": "CANCELLED", "can_resume": False},
                )
            else:
                has_parts = any(dest_dir.glob("*.part*")) if dest_dir.exists() else False
                await set_job(
                    job_id,
                    status="FAILED",
                    stage=f"FAILED: {exc.message}",
                    error=exc.message,
                    telemetry={"import_state": "FAILED", "can_resume": has_parts, "retry_count": int(opts.get("retry_count", 0)) + 1},
                )
            return
        except Exception as exc:  # noqa: BLE001
            await set_job(
                job_id,
                status="FAILED",
                stage=f"FAILED: {exc}",
                error=str(exc),
                telemetry={"import_state": "FAILED", "can_resume": True},
            )
            return

    # Release _import_sem() and URL dedup lock BEFORE running Whisper analysis so other URL downloads aren't blocked
    if active_url_imports.get(canon) == job_id:
        active_url_imports.pop(canon, None)
    if should_analyze:
        try:
            await run_pipeline(job_id, gemini_api_key=gemini_api_key, openai_api_key=openai_api_key)
        finally:
            cancelled.discard(job_id)
    else:
        cancelled.discard(job_id)


class _Cancelled(Exception):
    pass


def _check(job_id: str) -> None:
    if job_id in cancelled:
        raise _Cancelled()


# ------------------------------------------------------------------ analysis pipeline

async def run_pipeline(job_id: str, gemini_api_key: Optional[str] = None, openai_api_key: Optional[str] = None) -> None:
    async with _sem():
        cancelled.discard(job_id)
        async with async_session_maker() as s:
            job = (await s.execute(select(Job).where(Job.id == job_id).options(selectinload(Job.video)))).scalar_one_or_none()
            if not job or not job.video:
                return
            if job.status in ("cancelled", "CANCELLED"):
                return
            video, opts = job.video, dict(job.settings or {})
            video_id, src, duration = video.id, video.file_path, video.duration
        vid_dir = Path(settings.TEMP_DIR) / video_id
        work = vid_dir / "_work"
        wav = vid_dir / "audio_16k.wav"
        loop = asyncio.get_running_loop()
        warnings: List[str] = []
        try:
            if not Path(src).exists():
                raise RuntimeError("Source video file no longer exists on disk")
            vi.check_disk_space(int(duration * 32000))  # 16 kHz 16-bit mono WAV = 32 KB/s
            vid_dir.mkdir(parents=True, exist_ok=True)
            work.mkdir(parents=True, exist_ok=True)
            has_audio = bool(video.audio_codec)

            await set_job(
                job_id,
                status="analyzing",
                progress=5,
                stage="Extracting 16 kHz mono audio (FFmpeg)",
                error="",
                telemetry={"import_state": "COMPLETED", "total_audio_seconds": round(duration, 2)},
            )
            energy: List[float] = load_energy(video_id)
            if has_audio:
                last_ap = {"p": -1}

                def on_audio_prog(frac: float) -> None:
                    pct = 5 + int(frac * 6)
                    if pct != last_ap["p"]:
                        last_ap["p"] = pct
                        asyncio.run_coroutine_threadsafe(
                            set_job(job_id, progress=pct, stage=f"Extracting 16 kHz mono audio ({int(frac * 100)}%)"),
                            loop,
                        )

                ext_info = await asyncio.to_thread(
                    vp.extract_audio_wav,
                    src,
                    str(wav),
                    duration,
                    on_audio_prog,
                    lambda: job_id in cancelled,
                    True,
                )
                _check(job_id)
                if not energy or not ext_info.get("cached"):
                    energy = await asyncio.to_thread(transcription.compute_energy, str(wav))
                    save_energy(video_id, energy)
            else:
                warnings.append("Video has no audio track; no transcript or loudness analysis possible.")
            await set_job(
                job_id,
                progress=12,
                stage="Audio extracted & validated",
                last_completed_stage="audio",
                telemetry={"energy_window": 0.5},
            )

            segments: List[dict] = []
            detected_lang = opts.get("detected_language")
            detected_lang_prob = float(opts.get("detected_language_probability") or 0.0)
            model_used = (opts.get("whisper_model") or settings.WHISPER_MODEL or "base").strip().lower()
            profile_used = transcription.normalize_profile(opts.get("transcription_profile"))
            hw_info = transcription.detect_whisper_hardware()
            device_label = hw_info["label"]
            rtf_used = 0.0
            done_sec = 0.0

            if has_audio and opts.get("transcribe", True):
                # Check for resumable intermediate transcript checkpoint
                resume_sec = float(opts.get("last_transcribed_sec") or 0.0)
                initial_segs: List[dict] = []
                if resume_sec > 0.0:
                    async with async_session_maker() as s:
                        saved = (await s.execute(
                            select(TranscriptSegment)
                            .where(TranscriptSegment.video_id == video_id)
                            .order_by(TranscriptSegment.segment_index)
                        )).scalars().all()
                        if saved:
                            initial_segs = [
                                {
                                    "start": t.start_time,
                                    "end": t.end_time,
                                    "text": t.text,
                                    "confidence": t.confidence,
                                    "words": t.words,
                                }
                                for t in saved
                            ]
                else:
                    async with async_session_maker() as s:
                        await s.execute(delete(TranscriptSegment).where(TranscriptSegment.video_id == video_id))
                        await s.commit()

                await set_job(
                    job_id,
                    status="transcribing",
                    progress=15,
                    stage=f"Transcribing speech (Whisper {model_used} • {profile_used.title()} on {device_label})",
                    telemetry={
                        "whisper_model": model_used,
                        "whisper_profile": profile_used,
                        "whisper_device": device_label,
                        "elapsed_seconds": 0.0,
                        "transcribed_seconds": round(resume_sec, 2),
                        "total_audio_seconds": round(duration, 2),
                    },
                )
                last = {"p": -1, "t": 0.0}

                def on_telemetry(t: dict) -> None:
                    now = time.monotonic()
                    frac = float(t.get("progress_fraction", 0.0))
                    pct = 15 + int(frac * 55)
                    if pct != last["p"] or (now - last["t"]) >= 0.6:
                        last["p"] = pct
                        last["t"] = now
                        done_s = t.get("transcribed_seconds", 0.0)
                        tot_s = t.get("total_audio_seconds", duration)
                        rtf = t.get("realtime_factor", 0.0)
                        eta = t.get("eta_seconds")
                        el_s = t.get("elapsed_seconds", 0.0)
                        eta_s = f", ETA {int(eta)}s" if eta is not None else ""
                        lbl = (
                            f"Transcribing speech ({int(frac * 100)}% • "
                            f"{done_s:.0f}s/{tot_s:.0f}s • {model_used}/{profile_used} [{t.get('whisper_device', device_label)}] • "
                            f"{rtf:.1f}x RT{eta_s})"
                        )
                        asyncio.run_coroutine_threadsafe(
                            set_job(
                                job_id,
                                progress=pct,
                                stage=lbl,
                                telemetry={
                                    "transcribed_seconds": done_s,
                                    "total_audio_seconds": tot_s,
                                    "whisper_model": model_used,
                                    "whisper_profile": profile_used,
                                    "whisper_device": t.get("whisper_device", device_label),
                                    "realtime_factor": rtf,
                                    "elapsed_seconds": el_s,
                                    "eta_seconds": eta,
                                    "current_segment": t.get("current_segment"),
                                    "progress_percent": t.get("progress_percent"),
                                },
                            ),
                            loop,
                        )

                saved_count = [len(initial_segs)]

                async def _save_checkpoint(segs_snapshot: List[dict], sec_done: float) -> None:
                    start_idx = saved_count[0]
                    new_segs = segs_snapshot[start_idx:]
                    if not new_segs and start_idx > 0:
                        return
                    async with async_session_maker() as s:
                        for idx, seg in enumerate(new_segs):
                            s.add(TranscriptSegment(
                                video_id=video_id,
                                segment_index=start_idx + idx,
                                start_time=seg["start"],
                                end_time=seg["end"],
                                text=seg["text"],
                                confidence=seg["confidence"],
                                words=seg["words"],
                            ))
                        saved_count[0] = len(segs_snapshot)
                        j_row = await s.get(Job, job_id)
                        if j_row:
                            cur_s = dict(j_row.settings or {})
                            cur_s["last_transcribed_sec"] = round(sec_done, 2)
                            cur_s["can_resume"] = True
                            j_row.settings = cur_s
                        await s.commit()

                def on_checkpoint(segs_snapshot: List[dict], sec_done: float) -> None:
                    asyncio.run_coroutine_threadsafe(_save_checkpoint(list(segs_snapshot), sec_done), loop)

                transcription_completed = False
                try:
                    transcribe_res = await asyncio.to_thread(
                        transcription.transcribe_audio,
                        str(wav),
                        duration,
                        opts.get("language"),
                        None,
                        lambda: job_id in cancelled,
                        model_name=model_used,
                        telemetry_cb=on_telemetry,
                        checkpoint_cb=on_checkpoint,
                        resume_from_sec=resume_sec,
                        initial_segments=initial_segs,
                        profile=profile_used,
                    )
                    segments = list(transcribe_res)
                    if saved_count[0] < len(segments):
                        await _save_checkpoint(segments, duration)
                    detected_lang = getattr(transcribe_res, "language", None) or transcribe_res.get("language")
                    detected_lang_prob = getattr(transcribe_res, "language_probability", 0.0) or transcribe_res.get("language_probability", 0.0)
                    model_used = getattr(transcribe_res, "model_name", model_used) or transcribe_res.get("model_name", model_used)
                    device_label = getattr(transcribe_res, "device_label", device_label) or device_label
                    rtf_used = float(getattr(transcribe_res, "realtime_factor", 0.0) or 0.0)
                    transcription_completed = True
                except InterruptedError:
                    raise _Cancelled()
                except transcription.TranscriptionError as exc:
                    async with async_session_maker() as s:
                        saved = (await s.execute(
                            select(TranscriptSegment)
                            .where(TranscriptSegment.video_id == video_id)
                            .order_by(TranscriptSegment.segment_index)
                        )).scalars().all()
                        if saved:
                            segments = [
                                {
                                    "start": t.start_time,
                                    "end": t.end_time,
                                    "text": t.text,
                                    "confidence": t.confidence,
                                    "words": t.words,
                                }
                                for t in saved
                            ]
                    if segments:
                        warnings.append(f"Partial transcript preserved ({len(segments)} segments); remaining audio error: {exc}")
                    else:
                        warnings.append(f"Transcription unavailable, using audio-energy detection only: {exc}")
                if has_audio and not segments and not warnings:
                    warnings.append("No speech detected; clips are ranked by audio loudness only.")

                done_sec = round(duration, 2) if transcription_completed else (
                    round(segments[-1]["end"], 2) if segments else round(resume_sec, 2)
                )
                stage_label = f"Transcript saved ({detected_lang or 'unknown'}, {len(segments)} segments)" if segments else "No speech transcript"
                await set_job(
                    job_id,
                    progress=70,
                    stage=stage_label,
                    last_completed_stage="transcription",
                    detected_language=detected_lang,
                    telemetry={
                        "detected_language": detected_lang,
                        "detected_language_probability": detected_lang_prob,
                        "transcribed_seconds": done_sec,
                        "total_audio_seconds": round(duration, 2),
                        "whisper_model": model_used,
                        "whisper_device": device_label,
                        "realtime_factor": rtf_used,
                        "eta_seconds": 0.0,
                        "last_transcribed_sec": done_sec,
                    },
                )
            _check(job_id)

            await set_job(job_id, status="detecting", progress=78, stage="Detecting & scoring AI highlight moments")
            await replace_clips(job_id, segments, energy, duration, opts, gemini_api_key=gemini_api_key, openai_api_key=openai_api_key)
            async with async_session_maker() as s:
                n = len((await s.execute(select(Clip).where(Clip.job_id == job_id))).scalars().all())
            stage = f"Analysis complete: {n} candidate clip(s)" if n else "Analysis complete: no clips met the criteria"
            await set_job(
                job_id,
                status="ready",
                progress=100,
                stage=stage,
                last_completed_stage="detection",
                detected_language=detected_lang,
                settings={
                    **opts,
                    "import_state": "COMPLETED",
                    "energy_window": 0.5,
                    "warnings": warnings,
                    "detected_language": detected_lang,
                    "detected_language_probability": detected_lang_prob,
                    "whisper_model": model_used,
                    "whisper_device": device_label,
                    "realtime_factor": rtf_used,
                    "transcribed_seconds": done_sec,
                    "total_audio_seconds": round(duration, 2),
                    "last_transcribed_sec": done_sec,
                    "can_resume": False,
                },
            )
        except _Cancelled:
            await set_job(job_id, status="cancelled", stage="Cancelled by user", telemetry={"can_resume": True})
        except Exception as exc:  # noqa: BLE001 - surfaced to the user, never swallowed
            await set_job(job_id, status="failed", stage=f"Failed: {exc}", error=str(exc), telemetry={"can_resume": True})
        finally:
            cancelled.discard(job_id)
            shutil.rmtree(work, ignore_errors=True)


async def replace_clips(job_id: str, segments: List[dict], energy: List[float], duration: float, opts: dict,
                        gemini_api_key: Optional[str] = None, openai_api_key: Optional[str] = None) -> List[Clip]:
    """(Re)run AI or rule-based detection and replace clips that have not been exported."""
    g_key = gemini_api_key or opts.get("gemini_api_key") or getattr(settings, "GEMINI_API_KEY", None)
    o_key = openai_api_key or opts.get("openai_api_key") or getattr(settings, "OPENAI_API_KEY", None)
    cands = await asyncio.to_thread(
        clip_detector.detect_clips,
        segments, duration, energy, 0.5,
        min_len=float(opts.get("min_clip_seconds", 20)),
        max_len=float(opts.get("max_clip_seconds", 45)),
        target_len=float(opts.get("target_clip_seconds", 30)),
        max_clips=int(opts.get("max_clips", 5)),
        gemini_api_key=g_key,
        openai_api_key=o_key,
        use_ai_api=bool(opts.get("use_ai_api", True)),
    )
    rows_data = []
    for c in cands:
        clip_text = " ".join(seg.get("text", "") for seg in segments if seg.get("end", 0) >= c.start and seg.get("start", 0) <= c.end).strip()
        clip_words = []
        for seg in segments:
            if seg.get("end", 0) >= c.start and seg.get("start", 0) <= c.end and "words" in seg and seg["words"]:
                clip_words.extend(seg["words"])

        meta = await asyncio.to_thread(
            metadata_generator.generate_shorts_metadata,
            transcript_text=clip_text or c.title,
            duration=c.duration,
            start_time=c.start,
            end_time=c.end,
            category=c.category,
            words=clip_words,
            gemini_api_key=g_key,
            openai_api_key=o_key,
            use_ai_api=bool(opts.get("use_ai_api", True)),
        )
        rows_data.append((c, meta))

    async with async_session_maker() as s:
        await s.execute(delete(Clip).where(Clip.job_id == job_id, Clip.status.in_(("detected", "selected", "rejected"))))
        rows = []
        for c, meta in rows_data:
            rows.append(Clip(
                job_id=job_id,
                start_time=c.start,
                end_time=c.end,
                duration=c.duration,
                score=c.score,
                reason=c.reason,
                category=c.category,
                suggested_title=meta.get("recommended_title") or c.title,
                title_suggestions=meta.get("titles") or [c.title],
                suggested_description=meta.get("description") or c.description,
                hashtags=meta.get("hashtags") or c.hashtags,
                thumbnail_text=meta.get("thumbnail_text", ""),
                thumbnail_timestamp=meta.get("thumbnail_timestamp", c.start + c.duration * 0.42),
                layout="facecam_gameplay",
                facecam_crop={},
                gameplay_crop={},
                status="selected" if c.selected else "detected",
            ))
        s.add_all(rows)
        await s.commit()
        for r in rows:
            await s.refresh(r)
        return rows


# ------------------------------------------------------------------ export

def safe_filename(title: str, clip_id: str) -> str:
    base = re.sub(r"[^\w\- ]", "", title, flags=re.UNICODE).strip().replace(" ", "_")[:60] or "clip"
    return f"{base}_{clip_id}.mp4"


async def _set_clip(clip_id: str, **fields) -> None:
    async with async_session_maker() as s:
        clip = await s.get(Clip, clip_id)
        if clip:
            for k, v in fields.items():
                setattr(clip, k, v)
            await s.commit()


async def run_export(clip_id: str, opts: Dict[str, Any]) -> dict:
    """Render one clip. Raises ExportError on failure (clip is marked export_failed)."""
    async with async_session_maker() as s:
        clip = (await s.execute(select(Clip).where(Clip.id == clip_id))).scalar_one_or_none()
        if not clip:
            raise ExportError("Clip not found")
        job = (await s.execute(select(Job).where(Job.id == clip.job_id).options(selectinload(Job.video)))).scalar_one()
        video = job.video
        segs = (await s.execute(select(TranscriptSegment).where(TranscriptSegment.video_id == video.id)
                                .order_by(TranscriptSegment.start_time))).scalars().all()
        segments = [{"start": t.start_time, "end": t.end_time, "text": t.text, "words": t.words} for t in segs]
        start = float(opts.get("start_time", clip.start_time))
        end = float(opts.get("end_time", clip.end_time))
        title = opts.get("title") or clip.suggested_title
        layout = opts.get("layout") or clip.layout or "facecam_gameplay"
        fc = opts.get("facecam_crop") if opts.get("facecam_crop") is not None else clip.facecam_crop
        gp = opts.get("gameplay_crop") if opts.get("gameplay_crop") is not None else clip.gameplay_crop
        style = opts.get("subtitle_style") if opts.get("subtitle_style") is not None else clip.subtitle_style
        src, has_audio, job_id, vdur = video.file_path, bool(video.audio_codec), job.id, video.duration

    if not Path(src).exists():
        raise ExportError("Source video file no longer exists on disk")
    if not (0 <= start < end <= vdur + 0.05):
        raise ExportError(f"Clip range {start:.2f}-{end:.2f}s is outside the video (0-{vdur:.2f}s)")
    if layout not in vp.LAYOUTS:
        raise ExportError(f"Unknown layout '{layout}'")

    await _set_clip(clip_id, status="exporting", export_progress=0, export_error=None, suggested_title=title,
                    start_time=start, end_time=end, duration=round(end - start, 3), layout=layout,
                    facecam_crop=fc or {}, gameplay_crop=gp or {}, subtitle_style=style or {})
    loop = asyncio.get_running_loop()
    last = {"p": -1}

    def on_progress(frac: float) -> None:
        pct = int(frac * 99)
        if pct != last["p"]:
            last["p"] = pct
            asyncio.run_coroutine_threadsafe(_progress(clip_id, job_id, pct), loop)

    out_path = Path(settings.OUTPUT_DIR) / clip_id / safe_filename(title, clip_id)
    try:
        async with _export_sem():
            res = await asyncio.to_thread(
                render_clip, src, out_path, start, end, has_audio, layout, fc, gp, segments, style,
                bool(opts.get("burn_subtitles", True)), on_progress, lambda: clip_id in cancelled,
                bool(opts.get("prefer_hardware", True)),
                int(opts.get("fps") or vp.OUTPUT_FPS),
                opts.get("bitrate_kbps"),
                str(opts.get("quality") or "balanced"),
                int(opts.get("audio_bitrate_kbps") or 160),
                opts.get("preferred_encoder"),
            )
    except vp.Cancelled:
        await _set_clip(clip_id, status="detected", export_progress=0)
        await broadcast(clip_id, {"clip_id": clip_id, "status": "cancelled", "progress": 0})
        raise ExportError("Export cancelled")
    except (ExportError, ValueError, OSError) as exc:
        await _set_clip(clip_id, status="export_failed", export_error=str(exc))
        await broadcast(clip_id, {"clip_id": clip_id, "status": "export_failed", "progress": last["p"], "error": str(exc)})
        raise ExportError(str(exc))
    except Exception as exc:
        await _set_clip(clip_id, status="export_failed", export_error=str(exc))
        await broadcast(clip_id, {"clip_id": clip_id, "status": "export_failed", "progress": last["p"], "error": str(exc)})
        raise ExportError(str(exc)) from exc
    finally:
        cancelled.discard(clip_id)

    dl_url = f"/api/exports/{clip_id}/download"
    report = {
        **res["sync_report"],
        "encoder": res["encoder"]["label"],
        "encoder_codec": res["encoder"]["name"],
        "encoder_kind": res["encoder"]["kind"],
        "gpu_accelerated": res["gpu_accelerated"],
        "encoder_fallback_used": res["fallback_used"],
        "resolution": res["resolution"],
        "subtitle_words": res["subtitle_words"],
    }
    await _set_clip(
        clip_id,
        status="exported",
        export_progress=100,
        export_path=res["path"],
        export_url=dl_url,
        file_size_mb=res["size_mb"],
        sync_report=report,
    )
    await set_job(job_id, encoder_used=res["encoder"]["label"])
    await broadcast(clip_id, {"clip_id": clip_id, "status": "exported", "progress": 100})
    return {
        **res,
        "sync_report": report,
        "export_url": dl_url,
        "download_url": dl_url,
    }


async def _progress(clip_id: str, job_id: str, pct: int) -> None:
    await _set_clip(clip_id, export_progress=pct)
    await broadcast(clip_id, {"clip_id": clip_id, "job_id": job_id, "status": "exporting", "progress": pct})


# ------------------------------------------------------------------ startup recovery / cleanup

_NEW_COLUMNS = {
    "clips": [
        ("export_progress", "INTEGER DEFAULT 0"),
        ("export_error", "VARCHAR"),
        ("title_suggestions", "TEXT DEFAULT '[]'"),
        ("thumbnail_text", "VARCHAR DEFAULT ''"),
        ("thumbnail_timestamp", "FLOAT DEFAULT 0.0"),
    ],
    "jobs": [("detected_language", "VARCHAR")],
}


async def migrate_schema() -> None:
    """Create missing tables and add columns introduced after the database was first created."""
    import backend.app.models as _models
    _ = _models
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        for table, cols in _NEW_COLUMNS.items():
            existing = {r[1] for r in (await conn.execute(text(f"PRAGMA table_info({table})"))).all()}
            for name, ddl in cols:
                if existing and name not in existing:
                    await conn.execute(text(f"ALTER TABLE {table} ADD COLUMN {name} {ddl}"))
        await conn.execute(text("UPDATE jobs SET status=lower(status)"))


async def recover_interrupted() -> dict:
    """Jobs/exports that were mid-flight when the backend stopped cannot continue: mark them failed (with resume flag if partial exists)."""
    msg = "Interrupted by a backend restart. Press Restart to run it again."
    async with async_session_maker() as s:
        jobs = (await s.execute(select(Job).where(Job.status.in_(ACTIVE_STATUSES)))).scalars().all()
        for j in jobs:
            vid_dir = Path(settings.TEMP_DIR) / j.video_id
            has_resumable = (vid_dir / "upload_session.json").exists() or any(vid_dir.glob("*.part*")) if vid_dir.exists() else False
            opts = dict(j.settings or {})
            opts["can_resume"] = has_resumable
            opts["import_state"] = "FAILED"
            j.settings = opts
            j.status = "failed"
            j.error_message = msg
            j.current_stage = f"Failed: {msg}"
        clips = (await s.execute(select(Clip).where(Clip.status == "exporting"))).scalars().all()
        for c in clips:
            c.status, c.export_error = "export_failed", msg
        await s.commit()
        return {"jobs": len(jobs), "clips": len(clips)}


async def preflight_check() -> dict:
    """Run schema creation/migration, interrupted job recovery, and safe temp cleanup, then dispose DB pool."""
    from backend.app.cleanup import cleanup_storage
    await migrate_schema()
    recovered = await recover_interrupted()
    cleaned = await cleanup_storage()
    await engine.dispose()
    return {"recovered": recovered, "cleaned": cleaned}


def preflight_sync() -> dict:
    """Synchronous pre-flight check for Windows startup scripts (setup.bat / start.bat).
    Initializes SQLite tables, migrates columns, recovers interrupted jobs, and safely cleans stale temp files.
    """
    import sqlite3
    import time
    from sqlalchemy import create_engine as create_sync_engine
    import backend.app.models as _models
    _ = _models
    from backend.app.cleanup import ORPHAN_MIN_AGE_S

    db_file = Path(settings.DB_PATH)
    db_file.parent.mkdir(parents=True, exist_ok=True)
    sync_eng = create_sync_engine(f"sqlite:///{settings.DB_PATH}")
    Base.metadata.create_all(sync_eng)
    sync_eng.dispose()

    msg = "Interrupted by a backend restart. Press Restart to run it again."
    with sqlite3.connect(settings.DB_PATH) as conn:
        conn.execute("UPDATE jobs SET status=lower(status)")
        for table, cols in _NEW_COLUMNS.items():
            existing = {r[1] for r in conn.execute(f"PRAGMA table_info({table})").fetchall()}
            for name, ddl in cols:
                if existing and name not in existing:
                    conn.execute(f"ALTER TABLE {table} ADD COLUMN {name} {ddl}")
        placeholders = ",".join("?" for _ in ACTIVE_STATUSES)
        cur_j = conn.execute(
            f"UPDATE jobs SET status='failed', error_message=?, current_stage=? WHERE status IN ({placeholders})",
            (msg, f"Failed: {msg}", *ACTIVE_STATUSES),
        )
        cur_c = conn.execute(
            "UPDATE clips SET status='export_failed', export_error=? WHERE status='exporting'",
            (msg,),
        )
        known = {r[0] for r in conn.execute("SELECT id FROM videos").fetchall()}
        conn.commit()
        recovered = {"jobs": cur_j.rowcount, "clips": cur_c.rowcount}

    removed = {"orphan_dirs": 0, "work_dirs": 0, "partial_files": 0}
    now = time.time()
    temp = Path(settings.TEMP_DIR)
    temp.mkdir(parents=True, exist_ok=True)
    for d in temp.iterdir():
        if not d.is_dir():
            continue
        if d.name not in known and (now - d.stat().st_mtime) >= ORPHAN_MIN_AGE_S:
            shutil.rmtree(d, ignore_errors=True)
            removed["orphan_dirs"] += 1
            continue
        work = d / "_work"
        if work.exists() and (now - work.stat().st_mtime) >= ORPHAN_MIN_AGE_S:
            shutil.rmtree(work, ignore_errors=True)
            removed["work_dirs"] += 1

    out = Path(settings.OUTPUT_DIR)
    out.mkdir(parents=True, exist_ok=True)
    for p in out.rglob("*.part.mp4"):
        if (now - p.stat().st_mtime) >= ORPHAN_MIN_AGE_S:
            p.unlink(missing_ok=True)
            removed["partial_files"] += 1
    for d in out.rglob("render_*"):
        if d.is_dir() and (now - d.stat().st_mtime) >= ORPHAN_MIN_AGE_S:
            shutil.rmtree(d, ignore_errors=True)
            removed["work_dirs"] += 1

    return {"recovered": recovered, "cleaned": removed}
