"""High-performance video import & management endpoints:
- Resumable chunked upload protocol (/upload/init, /upload/{id}/chunk, /upload/{id}/status, /upload/{id}/complete, DELETE /upload/{id})
- Single-stream upload (/upload) with atomic .uploading.part finalization
- Background & synchronous authorized YouTube/Twitch URL imports (/import-url) with duplicate prevention & progress hooks
- HTTP Range streaming (/videos/{id}/stream) and full cleanup (DELETE /videos/{id}).
"""
import asyncio
import shutil
import uuid
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, Depends, File, Form, Header, HTTPException, Query, Request, UploadFile
from fastapi.responses import FileResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.app import job_runner, video_import as vi
from backend.app.config import settings
from backend.app.database import get_db
from backend.app.models.clip import Clip
from backend.app.models.job import Job
from backend.app.models.video import Video
from backend.app.schemas.video import (
    ChunkedUploadCompleteRequest,
    ChunkedUploadInitRequest,
    VideoImportUrlRequest,
)

router = APIRouter(prefix="/videos", tags=["Videos"])


def video_payload(video: Video, job_id: str | None = None, extra: dict | None = None) -> dict:
    out = {
        "id": video.id,
        "title": video.filename,
        "source_type": video.source_type,
        "video_url": f"/api/videos/{video.id}/stream",
        "duration": video.duration,
        "width": video.width,
        "height": video.height,
        "fps": video.fps,
        "is_vfr": video.is_vfr,
        "codec": video.codec,
        "audio_codec": video.audio_codec or None,
        "has_audio": bool(video.audio_codec),
        "file_size_mb": video.file_size_mb,
        "status": video.status,
    }
    if job_id:
        out["job_id"] = job_id
    if extra:
        out.update(extra)
    return out


async def store_upload(file: UploadFile, db: AsyncSession) -> Video:
    """Validate, stream directly to temporary .uploading.part file, atomically rename, probe with ffprobe and persist."""
    try:
        ext = vi.validate_extension(file.filename)
        vid_id = vi.new_video_id()
        dest_dir = vi.storage_dir_for(vid_id)
        dest = dest_dir / f"source{ext}"
        try:
            await vi.save_upload(file, dest)
        except BaseException:
            shutil.rmtree(dest_dir, ignore_errors=True)
            raise
        path, meta = await asyncio.to_thread(vi.ingest_local, file.filename, dest_dir, ext)
    except vi.ImportFailure as exc:
        raise HTTPException(status_code=exc.status, detail=exc.message)
    video = Video(
        id=vid_id,
        filename=vi.safe_display_name(file.filename),
        source_type="local",
        file_path=str(path),
        file_size_mb=meta.file_size_mb,
        duration=meta.duration,
        width=meta.width,
        height=meta.height,
        fps=meta.fps,
        is_vfr=meta.is_vfr,
        codec=meta.codec,
        audio_codec=meta.audio_codec or "",
        status="ready",
    )
    db.add(video)
    await db.commit()
    return video


async def create_job(db: AsyncSession, video_id: str, options: dict | None = None, *, start: bool = True,
                     gemini_api_key: str | None = None, openai_api_key: str | None = None) -> Job:
    clean_opts = dict(options or {})
    g_key = gemini_api_key or clean_opts.pop("gemini_api_key", None)
    o_key = openai_api_key or clean_opts.pop("openai_api_key", None)
    job = Job(
        id=f"job_{uuid.uuid4().hex[:12]}",
        video_id=video_id,
        status="queued" if start else "completed",
        progress=0 if start else 100,
        current_stage="Queued for analysis" if start else "COMPLETED: Video imported and metadata extracted",
        settings=clean_opts,
    )
    db.add(job)
    await db.commit()
    if start:
        job_runner.start_pipeline(job.id, gemini_api_key=g_key, openai_api_key=o_key)
    return job


# ------------------------------------------------------------------ Resumable Chunked Upload Endpoints

@router.post("/upload/init", status_code=201)
async def init_upload(req: ChunkedUploadInitRequest, db: AsyncSession = Depends(get_db)):
    """Initialize or resume a high-performance chunked upload session for large (3-4+ hour) videos."""
    g_key = req.gemini_api_key
    o_key = req.openai_api_key
    opts = {k: v for k, v in {
        "whisper_model": req.whisper_model,
        "auto_analyze": req.auto_analyze,
    }.items() if v is not None}

    try:
        session = await asyncio.to_thread(
            vi.init_chunked_upload,
            filename=req.filename,
            total_bytes=req.total_bytes,
            chunk_size=req.chunk_size,
            fingerprint=req.fingerprint,
            file_sha256=req.file_sha256,
            auto_analyze=req.auto_analyze,
            options={**opts, "gemini_api_key": g_key, "openai_api_key": o_key},
        )
    except vi.ImportFailure as exc:
        raise HTTPException(status_code=exc.status, detail=exc.message)

    vid_id = session["video_id"]
    job_id = session["job_id"]

    existing_video = (await db.execute(select(Video).where(Video.id == vid_id))).scalar_one_or_none()
    if not existing_video:
        video = Video(
            id=vid_id,
            filename=session["filename"],
            source_type="local",
            file_path=session["part_path"],
            file_size_mb=round(req.total_bytes / 1048576, 2),
            status="uploading",
        )
        db.add(video)
        job = Job(
            id=job_id,
            video_id=vid_id,
            status="initializing",
            progress=0,
            current_stage="INITIALIZING: Upload session ready",
            settings={
                **opts,
                "import_state": "INITIALIZING",
                "upload_id": vid_id,
                "total_bytes": req.total_bytes,
                "bytes_transferred": session.get("bytes_received", 0),
                "total_chunks": session["total_chunks"],
                "chunks_received": len(session.get("received_chunks", {})),
                "can_resume": True,
            },
        )
        db.add(job)
        await db.commit()
    else:
        await job_runner.set_job(
            job_id,
            status="uploading",
            stage="UPLOADING: Resumed chunked upload",
            error="",
            telemetry={"import_state": "UPLOADING", "can_resume": True},
        )

    received_indices = sorted(int(k) for k in session.get("received_chunks", {}).keys())
    return {
        "upload_id": session["upload_id"],
        "video_id": vid_id,
        "job_id": job_id,
        "chunk_size": session["chunk_size"],
        "total_chunks": session["total_chunks"],
        "total_bytes": session["total_bytes"],
        "bytes_received": session.get("bytes_received", 0),
        "received_chunks": received_indices,
        "resumed": bool(session.get("resumed", False)),
        "status": session.get("status", "UPLOADING"),
    }


@router.put("/upload/{upload_id}/chunk")
@router.post("/upload/{upload_id}/chunk")
async def upload_chunk(
    upload_id: str,
    request: Request,
    chunk_index: int = Query(..., ge=0),
    offset: Optional[int] = Query(None, ge=0),
    sha256: Optional[str] = Query(None),
    x_chunk_sha256: Optional[str] = Header(None),
    chunk: Optional[UploadFile] = File(None),
):
    """Receive, verify, deduplicate, and write a single chunk directly to the temporary .uploading.part file."""
    if chunk is not None:
        data = await chunk.read()
    else:
        data = await request.body()

    expected_hash = sha256 or x_chunk_sha256
    try:
        sess = vi.get_upload_session(upload_id)
        job_id = sess["job_id"]
        res = await asyncio.to_thread(
            vi.write_upload_chunk,
            upload_id=upload_id,
            chunk_index=chunk_index,
            data=data,
            offset=offset,
            expected_sha256=expected_hash,
            should_cancel=lambda: job_id in job_runner.cancelled,
        )
    except vi.ImportFailure as exc:
        raise HTTPException(status_code=exc.status, detail=exc.message)

    mb_done = res["bytes_received"] / 1048576
    mb_tot = res["total_bytes"] / 1048576
    mb_s = res["speed_bps"] / 1048576
    eta_str = f", ETA {int(res['eta_seconds'])}s" if res.get("eta_seconds") is not None else ""
    stage_label = f"UPLOADING: {mb_done:.1f}/{mb_tot:.1f} MB ({mb_s:.1f} MB/s{eta_str})"

    await job_runner.set_job(
        res["job_id"],
        status="UPLOADING",
        progress=res["progress"],
        stage=stage_label,
        telemetry={
            "import_state": "UPLOADING",
            "bytes_transferred": res["bytes_received"],
            "total_bytes": res["total_bytes"],
            "speed_bps": res["speed_bps"],
            "eta_seconds": res["eta_seconds"],
            "chunks_received": res["chunks_received"],
            "total_chunks": res["total_chunks"],
            "can_resume": True,
        },
    )
    return res


@router.get("/upload/{upload_id}/status")
async def get_upload_status(upload_id: str):
    """Return received chunks and byte progress so interrupted uploads can resume cleanly."""
    try:
        session = vi.get_upload_session(upload_id)
    except vi.ImportFailure as exc:
        raise HTTPException(status_code=exc.status, detail=exc.message)
    received_indices = sorted(int(k) for k in session.get("received_chunks", {}).keys())
    total_b = max(1, int(session["total_bytes"]))
    bytes_rec = int(session.get("bytes_received", 0))
    return {
        "upload_id": upload_id,
        "video_id": session["video_id"],
        "job_id": session["job_id"],
        "status": session.get("status", "UPLOADING"),
        "bytes_received": bytes_rec,
        "total_bytes": session["total_bytes"],
        "chunks_received": len(received_indices),
        "total_chunks": session["total_chunks"],
        "received_chunks": received_indices,
        "progress": min(99, int((bytes_rec / total_b) * 100)),
    }


@router.post("/upload/{upload_id}/complete")
async def complete_upload(
    upload_id: str,
    req: Optional[ChunkedUploadCompleteRequest] = None,
    db: AsyncSession = Depends(get_db),
):
    """Verify final file integrity, atomically rename .uploading.part -> source.<ext>, and extract FFprobe metadata."""
    try:
        sess = vi.get_upload_session(upload_id)
    except vi.ImportFailure as exc:
        raise HTTPException(status_code=exc.status, detail=exc.message)

    job_id = sess["job_id"]
    vid_id = sess["video_id"]
    loop = asyncio.get_running_loop()

    def on_stage(stage: str, pct: int, msg: str) -> None:
        asyncio.run_coroutine_threadsafe(
            job_runner.set_job(
                job_id,
                status=stage,
                progress=pct,
                stage=f"{stage}: {msg}",
                telemetry={"import_state": stage},
            ),
            loop,
        )

    try:
        final_path, meta, session = await asyncio.to_thread(
            vi.finalize_chunked_upload,
            upload_id=upload_id,
            expected_sha256=req.file_sha256 if req else None,
            on_stage=on_stage,
        )
    except vi.ImportFailure as exc:
        await job_runner.set_job(
            job_id,
            status="FAILED",
            stage=f"FAILED: {exc.message}",
            error=exc.message,
            telemetry={"import_state": "FAILED"},
        )
        raise HTTPException(status_code=exc.status, detail=exc.message)

    video = await db.get(Video, vid_id)
    if not video:
        video = Video(id=vid_id, filename=session["filename"], source_type="local", file_path=str(final_path))
        db.add(video)

    video.file_path = str(final_path)
    video.file_size_mb = meta.file_size_mb
    video.duration = meta.duration
    video.width = meta.width
    video.height = meta.height
    video.fps = meta.fps
    video.is_vfr = meta.is_vfr
    video.codec = meta.codec
    video.audio_codec = meta.audio_codec or ""
    video.status = "ready"
    await db.commit()

    await job_runner.set_job(
        job_id,
        status="COMPLETED",
        progress=100,
        stage="COMPLETED: Upload verified and metadata extracted",
        last_completed_stage="import",
        telemetry={
            "import_state": "COMPLETED",
            "bytes_transferred": meta.file_size_bytes,
            "total_bytes": meta.file_size_bytes,
            "speed_bps": 0.0,
            "eta_seconds": 0.0,
            "can_resume": False,
        },
    )

    auto_analyze = req.auto_analyze if (req and req.auto_analyze is not None) else session.get("auto_analyze", False)
    if auto_analyze:
        sess_opts = session.get("options") or {}
        g_key = session.get("gemini_api_key") or sess_opts.get("gemini_api_key")
        o_key = session.get("openai_api_key") or sess_opts.get("openai_api_key")
        job_runner.start_pipeline(job_id, gemini_api_key=g_key, openai_api_key=o_key)

    return video_payload(video, job_id, {"import_state": "COMPLETED", "auto_analyze": bool(auto_analyze)})


@router.delete("/upload/{upload_id}")
async def cancel_upload_session(upload_id: str, db: AsyncSession = Depends(get_db)):
    """Cancel an in-progress chunked upload and safely remove its temporary .uploading.part file."""
    res = await asyncio.to_thread(vi.cancel_chunked_upload, upload_id)
    job_id = res.get("job_id")
    if job_id:
        job_runner.cancelled.add(job_id)
        await job_runner.set_job(
            job_id,
            status="CANCELLED",
            stage="CANCELLED: Upload cancelled by user",
            telemetry={"import_state": "CANCELLED", "can_resume": False},
        )
    video = await db.get(Video, upload_id)
    if video and video.status == "uploading":
        await db.delete(video)
        await db.commit()
    return res


# ------------------------------------------------------------------ Single-Request Upload & URL Import

@router.post("/upload")
async def upload_video(
    file: UploadFile = File(...),
    language: str | None = Form(None),
    whisper_model: str | None = Form(None),
    gemini_api_key: str | None = Form(None),
    openai_api_key: str | None = Form(None),
    auto_analyze: bool = Form(True),
    db: AsyncSession = Depends(get_db),
):
    """Upload + validate + probe (streaming to .uploading.part then atomic rename)."""
    video = await store_upload(file, db)
    opts = {k: v for k, v in {
        "language": language,
        "whisper_model": whisper_model,
        "import_state": "COMPLETED",
    }.items() if v}
    job = await create_job(db, video.id, opts, start=auto_analyze, gemini_api_key=gemini_api_key, openai_api_key=openai_api_key)
    return video_payload(video, job.id, {"import_state": "COMPLETED"})


@router.post("/import-url")
async def import_url(req: VideoImportUrlRequest, db: AsyncSession = Depends(get_db)):
    """Import an authorized public YouTube/Twitch video via yt-dlp.

    - Validates URL host and yt-dlp availability synchronously.
    - Prevents duplicate concurrent download jobs for the same URL.
    - Runs download in a background worker (when req.background=True) with real-time WebSocket progress hooks,
      or synchronously when req.background=False.
    """
    clean_url = req.url.strip()
    try:
        platform = vi.classify_url(clean_url)
        vi.check_disk_space(0)
        if not vi.ytdlp_available():
            raise vi.ImportFailure(
                "yt-dlp is not installed on the server, so URL import is unavailable. "
                "Upload the video file instead, or install yt-dlp.",
                503,
            )
    except vi.ImportFailure as exc:
        raise HTTPException(status_code=exc.status, detail=exc.message)

    # Prevent duplicate active download jobs for the same URL
    active_jid = job_runner.get_active_url_job(clean_url)
    if active_jid:
        existing_job = await db.get(Job, active_jid)
        if existing_job:
            existing_vid = await db.get(Video, existing_job.video_id)
            if existing_vid:
                return video_payload(
                    existing_vid,
                    existing_job.id,
                    {"import_state": existing_job.status, "duplicate_prevented": True},
                )

    opts = {k: v for k, v in {
        "language": req.language,
        "whisper_model": req.whisper_model,
        "auto_analyze": req.auto_analyze,
        "source_url": clean_url,
    }.items() if v is not None}

    if not req.background:
        vid_id = vi.new_video_id()
        dest_dir = vi.storage_dir_for(vid_id)
        try:
            path, meta, platform, title = await asyncio.to_thread(vi.import_external, clean_url, dest_dir)
        except vi.ImportFailure as exc:
            shutil.rmtree(dest_dir, ignore_errors=True)
            raise HTTPException(status_code=exc.status, detail=exc.message)
        video = Video(
            id=vid_id,
            filename=title,
            source_type=platform,
            original_url=clean_url,
            file_path=str(path),
            file_size_mb=meta.file_size_mb,
            duration=meta.duration,
            width=meta.width,
            height=meta.height,
            fps=meta.fps,
            is_vfr=meta.is_vfr,
            codec=meta.codec,
            audio_codec=meta.audio_codec or "",
            status="ready",
        )
        db.add(video)
        await db.commit()
        job = await create_job(db, video.id, {**opts, "import_state": "COMPLETED"}, start=req.auto_analyze,
                               gemini_api_key=req.gemini_api_key, openai_api_key=req.openai_api_key)
        return video_payload(video, job.id, {"import_state": "COMPLETED"})

    # Background worker execution (keeps FastAPI responsive for 3-4h VODs)
    vid_id = vi.new_video_id()
    dest_dir = vi.storage_dir_for(vid_id)
    platform_title = "YouTube" if platform == "youtube" else platform.title()
    video = Video(
        id=vid_id,
        filename=f"{platform_title} Stream Import",
        source_type=platform,
        original_url=clean_url,
        file_path=str(dest_dir / "source.mp4"),
        status="downloading",
    )
    db.add(video)
    job = Job(
        id=f"job_{uuid.uuid4().hex[:12]}",
        video_id=vid_id,
        status="queued",
        progress=0,
        current_stage="QUEUED: Waiting to start stream download",
        settings={**opts, "import_state": "QUEUED", "can_resume": True},
    )
    db.add(job)
    await db.commit()
    job_runner.start_url_import(job.id, clean_url, gemini_api_key=req.gemini_api_key, openai_api_key=req.openai_api_key)
    return video_payload(video, job.id, {"import_state": "QUEUED", "duplicate_prevented": False})


async def _get_video(db: AsyncSession, id: str) -> Video:
    video = (await db.execute(select(Video).where(Video.id == id))).scalar_one_or_none()
    if not video:
        raise HTTPException(status_code=404, detail="Video not found")
    return video


@router.get("/{id}")
async def get_video(id: str, db: AsyncSession = Depends(get_db)):
    return video_payload(await _get_video(db, id))


@router.get("/{id}/stream")
async def stream_video(id: str, db: AsyncSession = Depends(get_db)):
    video = await _get_video(db, id)
    if not Path(video.file_path).exists():
        raise HTTPException(status_code=404, detail="Source video file not found on disk")
    media = {
        ".mp4": "video/mp4",
        ".mov": "video/quicktime",
        ".webm": "video/webm",
        ".mkv": "video/x-matroska",
        ".avi": "video/x-msvideo",
    }.get(Path(video.file_path).suffix.lower(), "video/mp4")
    return FileResponse(video.file_path, media_type=media)  # supports HTTP Range for scrubbing


async def purge_video(db: AsyncSession, video: Video) -> None:
    """Delete a video, its jobs/clips, the source file and every rendered export."""
    clip_ids = (
        await db.execute(select(Clip.id).join(Job, Clip.job_id == Job.id).where(Job.video_id == video.id))
    ).scalars().all()
    for cid in clip_ids:
        shutil.rmtree(Path(settings.OUTPUT_DIR) / cid, ignore_errors=True)
    shutil.rmtree(Path(settings.TEMP_DIR) / video.id, ignore_errors=True)
    await db.delete(video)
    await db.commit()


@router.delete("/{id}")
async def delete_video(id: str, db: AsyncSession = Depends(get_db)):
    video = await _get_video(db, id)
    await purge_video(db, video)
    return {"message": "Video and all derived files deleted"}
