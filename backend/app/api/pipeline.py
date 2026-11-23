"""Pipeline endpoints: POST /api/upload, /api/analyze, /api/clips/generate, GET /api/clips/{id}, POST /api/export."""
import asyncio
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, UploadFile, File
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.app import job_runner, metadata_generator, translation, video_processor as vp
from backend.app.api.serializers import clip_to_dict
from backend.app.api.videos import create_job, store_upload, video_payload
from backend.app.database import get_db
from backend.app.models.clip import Clip
from backend.app.models.job import Job
from backend.app.models.transcript import TranscriptSegment
from backend.app.models.video import Video
from backend.app.schemas.clip import ClipMetadataRequest, ClipTranscriptUpdate, ClipTranslateRequest, ClipUpdate
from backend.app.schemas.pipeline import AnalyzeRequest, BatchExportRequest, ExportRequest, GenerateClipsRequest

router = APIRouter(tags=["Pipeline"])
_active_clip_translations: set[str] = set()


@router.post("/upload", status_code=201)
async def upload(file: UploadFile = File(...), db: AsyncSession = Depends(get_db)):
    """Store and validate a local video (no processing yet). Returns real ffprobe metadata."""
    return video_payload(await store_upload(file, db))


@router.post("/analyze", status_code=202)
async def analyze(req: AnalyzeRequest, db: AsyncSession = Depends(get_db)):
    """Queue transcription + moment detection for an uploaded video. Poll GET /api/jobs/{job_id}."""
    if not (await db.execute(select(Video.id).where(Video.id == req.video_id))).scalar_one_or_none():
        raise HTTPException(status_code=404, detail="Video not found")
    job = await create_job(db, req.video_id, req.model_dump(exclude={"video_id"}))
    return {"job_id": job.id, "status": job.status, "progress": job.progress, "status_url": f"/api/jobs/{job.id}"}


@router.post("/clips/generate")
async def generate_clips(req: GenerateClipsRequest, db: AsyncSession = Depends(get_db)):
    """Re-rank clips from the stored transcript/audio analysis with new constraints (fast, no re-transcription)."""
    job = (await db.execute(select(Job).where(Job.id == req.job_id))).scalar_one_or_none()
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    if job.status != "ready":
        raise HTTPException(status_code=409, detail=f"Analysis is not finished (status: {job.status})")
    video = await db.get(Video, job.video_id)
    segs = (await db.execute(select(TranscriptSegment).where(TranscriptSegment.video_id == job.video_id)
                             .order_by(TranscriptSegment.start_time))).scalars().all()
    segments = [{"start": t.start_time, "end": t.end_time, "text": t.text, "words": t.words} for t in segs]
    opts = dict(job.settings or {})
    energy = job_runner.load_energy(job.video_id)
    clips = await job_runner.replace_clips(job.id, segments, energy, video.duration, req.model_dump(exclude={"job_id"}))
    opts.update(req.model_dump(exclude={"job_id"}))
    job.settings = opts
    await db.commit()
    exported = (await db.execute(select(Clip).where(Clip.job_id == job.id, Clip.status == "exported"))).scalars().all()
    return {"job_id": job.id, "clips": [clip_to_dict(c) for c in sorted([*clips, *exported], key=lambda c: -c.score)]}


@router.get("/clips/{clip_id}")
async def get_clip(clip_id: str, db: AsyncSession = Depends(get_db)):
    clip = (await db.execute(select(Clip).where(Clip.id == clip_id))).scalar_one_or_none()
    if not clip:
        raise HTTPException(status_code=404, detail="Clip not found")
    job = await db.get(Job, clip.job_id)
    segs = (await db.execute(select(TranscriptSegment).where(
        TranscriptSegment.video_id == job.video_id, TranscriptSegment.end_time >= clip.start_time,
        TranscriptSegment.start_time <= clip.end_time).order_by(TranscriptSegment.start_time))).scalars().all()
    return {**clip_to_dict(clip),
            "detected_language": getattr(job, "detected_language", None) or (job.settings or {}).get("detected_language"),
            "transcript": [{"id": t.id, "start": t.start_time, "end": t.end_time, "text": t.text, "words": t.words} for t in segs]}


@router.put("/clips/{clip_id}/transcript")
async def update_clip_transcript(clip_id: str, req: ClipTranscriptUpdate, db: AsyncSession = Depends(get_db)):
    """Allow manual transcript correction for segments covering this clip."""
    clip = (await db.execute(select(Clip).where(Clip.id == clip_id))).scalar_one_or_none()
    if not clip:
        raise HTTPException(status_code=404, detail="Clip not found")
    job = await db.get(Job, clip.job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")

    for s_in in req.segments:
        seg = None
        if s_in.id:
            seg = await db.get(TranscriptSegment, s_in.id)
        elif s_in.start is not None and s_in.end is not None:
            seg = (await db.execute(select(TranscriptSegment).where(
                TranscriptSegment.video_id == job.video_id,
                TranscriptSegment.start_time >= s_in.start - 0.15,
                TranscriptSegment.start_time <= s_in.start + 0.15))).scalar_one_or_none()

        if seg and seg.video_id == job.video_id:
            seg.text = s_in.text.strip()
            if s_in.words:
                seg.words = [w.model_dump() for w in s_in.words]
            else:
                toks = seg.text.split()
                if toks:
                    step = (seg.end_time - seg.start_time) / len(toks)
                    seg.words = [{"word": t, "start": round(seg.start_time + i * step, 3),
                                  "end": round(seg.start_time + (i + 1) * step, 3), "probability": 1.0}
                                 for i, t in enumerate(toks)]
            db.add(seg)

    await db.commit()
    segs = (await db.execute(select(TranscriptSegment).where(
        TranscriptSegment.video_id == job.video_id, TranscriptSegment.end_time >= clip.start_time,
        TranscriptSegment.start_time <= clip.end_time).order_by(TranscriptSegment.start_time))).scalars().all()
    return {"clip_id": clip.id,
            "transcript": [{"id": t.id, "start": t.start_time, "end": t.end_time, "text": t.text, "words": t.words} for t in segs]}


@router.patch("/clips/{clip_id}")
async def update_clip(clip_id: str, req: ClipUpdate, db: AsyncSession = Depends(get_db)):
    """Allow user to adjust start/end timestamps, title, category, or crop parameters."""
    clip = (await db.execute(select(Clip).where(Clip.id == clip_id))).scalar_one_or_none()
    if not clip:
        raise HTTPException(status_code=404, detail="Clip not found")
    job = await db.get(Job, clip.job_id)
    video = await db.get(Video, job.video_id)

    data = req.model_dump(exclude_unset=True)
    new_start = data.get("start_time", clip.start_time)
    new_end = data.get("end_time", clip.end_time)

    if new_start is not None and new_end is not None:
        if new_start < 0:
            raise HTTPException(status_code=422, detail="start_time cannot be negative")
        if new_end <= new_start:
            raise HTTPException(status_code=422, detail="end_time must be greater than start_time")
        if video and new_end > video.duration + 0.1:
            raise HTTPException(status_code=422, detail=f"end_time exceeds video duration ({video.duration:.2f}s)")
        clip.start_time = round(float(new_start), 3)
        clip.end_time = round(float(new_end), 3)
        clip.duration = round(clip.end_time - clip.start_time, 3)

    if "layout" in data and data["layout"] is not None and data["layout"] not in vp.LAYOUTS:
        raise HTTPException(status_code=422, detail=f"Unknown layout '{data['layout']}'. Choose from {', '.join(vp.LAYOUTS)}")

    for k, v in data.items():
        if k not in ("start_time", "end_time") and hasattr(clip, k):
            setattr(clip, k, v)

    await db.commit()
    await db.refresh(clip)
    return clip_to_dict(clip)


@router.post("/clips/{clip_id}/metadata")
async def generate_clip_metadata(
    clip_id: str,
    req: Optional[ClipMetadataRequest] = None,
    db: AsyncSession = Depends(get_db),
):
    """Generate or regenerate AI YouTube Shorts metadata based strictly on actual clip transcript."""
    clip = (await db.execute(select(Clip).where(Clip.id == clip_id))).scalar_one_or_none()
    if not clip:
        raise HTTPException(status_code=404, detail="Clip not found")
    job = await db.get(Job, clip.job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Associated job not found")

    segs = (await db.execute(
        select(TranscriptSegment)
        .where(
            TranscriptSegment.video_id == job.video_id,
            TranscriptSegment.end_time >= clip.start_time,
            TranscriptSegment.start_time <= clip.end_time,
        )
        .order_by(TranscriptSegment.start_time)
    )).scalars().all()

    clip_text = " ".join(s.text for s in segs).strip()
    words = []
    for s in segs:
        if s.words:
            words.extend(s.words)

    opts = req.model_dump() if req else {}
    job_opts = dict(job.settings or {})
    gkey = opts.get("gemini_api_key") or job_opts.get("gemini_api_key")
    okey = opts.get("openai_api_key") or job_opts.get("openai_api_key")
    use_ai = opts.get("use_ai_api", True)

    meta = metadata_generator.generate_shorts_metadata(
        transcript_text=clip_text or clip.suggested_title,
        duration=clip.duration,
        start_time=clip.start_time,
        end_time=clip.end_time,
        category=clip.category,
        words=words,
        gemini_api_key=gkey,
        openai_api_key=okey,
        use_ai_api=use_ai,
    )

    clip.suggested_title = meta["recommended_title"]
    clip.title_suggestions = meta["titles"]
    clip.suggested_description = meta["description"]
    clip.hashtags = meta["hashtags"]
    clip.thumbnail_text = meta["thumbnail_text"]
    clip.thumbnail_timestamp = meta["thumbnail_timestamp"]

    await db.commit()
    await db.refresh(clip)
    return clip_to_dict(clip)


@router.get("/languages")
async def get_languages():
    """List supported languages for audio detection, transcription and subtitle translation."""
    return translation.SUPPORTED_LANGUAGES


@router.post("/clips/{clip_id}/translate")
async def translate_clip_subtitles(
    clip_id: str,
    req: ClipTranslateRequest,
    db: AsyncSession = Depends(get_db),
):
    """Translate clip subtitles into target language while preserving speech timing & original transcript."""
    clip = (await db.execute(select(Clip).where(Clip.id == clip_id))).scalar_one_or_none()
    if not clip:
        raise HTTPException(status_code=404, detail="Clip not found")
    job = await db.get(Job, clip.job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Associated job not found")

    target_lang = translation.normalize_language_code(req.target_language)
    source_lang = getattr(job, "detected_language", None) or (job.settings or {}).get("detected_language")

    # If resetting to original
    if target_lang in ("original", "source", "none", ""):
        st = dict(clip.subtitle_style or {})
        for k in (
            "translated_words",
            "translatedWords",
            "translated_segments",
            "translatedSegments",
            "translation_provider",
            "translationProvider",
            "translation_partial",
            "translation_warnings",
        ):
            st.pop(k, None)
        st["is_translated"] = False
        st["isTranslated"] = False
        st["subtitle_language"] = "original"
        st["subtitleLanguage"] = "original"
        clip.subtitle_style = st
        await db.commit()
        await db.refresh(clip)
        return {
            "clip_id": clip.id,
            "source_language": source_lang or "auto",
            "target_language": "original",
            "provider": "original",
            "partial": False,
            "warnings": [],
            "translated_segments": [],
            "translated_words": [],
            "subtitle_style": clip.subtitle_style,
        }

    # Prevent duplicate concurrent translation requests for the same clip
    if clip_id in _active_clip_translations:
        raise HTTPException(status_code=409, detail="Subtitle translation is already in progress for this clip.")
    _active_clip_translations.add(clip_id)

    try:
        # Fetch original segments for this clip (read-only; original transcript is never modified)
        segs = (await db.execute(
            select(TranscriptSegment)
            .where(
                TranscriptSegment.video_id == job.video_id,
                TranscriptSegment.end_time >= clip.start_time,
                TranscriptSegment.start_time <= clip.end_time,
            )
            .order_by(TranscriptSegment.start_time)
        )).scalars().all()

        seg_dicts = [
            {
                "id": s.id,
                "start": s.start_time,
                "end": s.end_time,
                "text": s.text,
                "confidence": s.confidence,
                "words": s.words,
            }
            for s in segs
        ]

        job_opts = dict(job.settings or {})
        gkey = req.gemini_api_key or job_opts.get("gemini_api_key")
        okey = req.openai_api_key or job_opts.get("openai_api_key")

        try:
            result = await asyncio.to_thread(
                translation.translate_clip_segments,
                seg_dicts,
                target_lang,
                source_lang,
                gemini_api_key=gkey,
                openai_api_key=okey,
            )
        except translation.TranslationError as exc:
            raise HTTPException(status_code=exc.status_code, detail=exc.message)

        # Store translated subtitles separately inside clip.subtitle_style (original TranscriptSegment rows untouched)
        st = dict(clip.subtitle_style or {})
        st.pop("translatedWords", None)
        st.pop("translatedSegments", None)
        st["subtitle_language"] = result.target_language
        st["subtitleLanguage"] = result.target_language
        st["source_language"] = result.source_language
        st["is_translated"] = True
        st["isTranslated"] = True
        st["translated_segments"] = result.segments
        st["translated_words"] = result.words
        st["translation_provider"] = result.provider
        st["translation_partial"] = result.partial
        st["translation_warnings"] = result.warnings

        sample_text = " ".join(w["word"] for w in result.words[:10]) if result.words else ""
        resolved_font = translation.resolve_font_for_script(sample_text, st.get("font") or st.get("fontFamily") or "Arial")
        st["font"] = resolved_font
        st["fontFamily"] = resolved_font
        if translation.detect_script(sample_text) != "latin":
            st["uppercase"] = False
            st["isUppercase"] = False

        clip.subtitle_style = st
        await db.commit()
        await db.refresh(clip)

        return {
            "clip_id": clip.id,
            "source_language": result.source_language,
            "target_language": result.target_language,
            "provider": result.provider,
            "partial": result.partial,
            "warnings": result.warnings,
            "translated_segments": result.segments,
            "translated_words": result.words,
            "subtitle_style": clip.subtitle_style,
        }
    finally:
        _active_clip_translations.discard(clip_id)


@router.post("/clips/{clip_id}/smart-crop")
async def analyze_smart_crop(clip_id: str, db: AsyncSession = Depends(get_db)):
    """Run OpenCV face/subject detection and trajectory tracking on a clip's time window."""
    clip = (await db.execute(select(Clip).where(Clip.id == clip_id))).scalar_one_or_none()
    if not clip:
        raise HTTPException(status_code=404, detail="Clip not found")
    job = await db.get(Job, clip.job_id)
    video = await db.get(Video, job.video_id)
    if not video:
        raise HTTPException(status_code=404, detail="Source video not found")
    comp = await asyncio.to_thread(vp.analyze_video_composition, video.file_path, clip.start_time, clip.end_time)
    if comp.get("auto_facecam_crop") and not clip.facecam_crop:
        clip.facecam_crop = comp["auto_facecam_crop"]
        await db.commit()
    return {"clip_id": clip.id, **comp}


@router.post("/export", status_code=202)
async def export(req: ExportRequest, db: AsyncSession = Depends(get_db)):
    """Start a background render. Poll GET /api/clips/{clip_id} (export_progress/status) or use the WebSocket."""
    clip = (await db.execute(select(Clip).where(Clip.id == req.clip_id))).scalar_one_or_none()
    if not clip:
        raise HTTPException(status_code=404, detail="Clip not found")
    if clip.status == "exporting":
        raise HTTPException(status_code=409, detail="This clip is already being exported")
    opts = req.model_dump(exclude={"clip_id"}, exclude_none=True)
    start, end = opts.get("start_time", clip.start_time), opts.get("end_time", clip.end_time)
    if end <= start or end - start < 3 or end - start > 180:
        raise HTTPException(status_code=422, detail="Clip length must be between 3 and 180 seconds")
    job = await db.get(Job, clip.job_id)
    video = await db.get(Video, job.video_id)
    if end > video.duration + 0.05:
        raise HTTPException(status_code=422, detail=f"end_time exceeds video duration ({video.duration:.2f}s)")
    clip.status, clip.export_progress, clip.export_error = "exporting", 0, None
    await db.commit()

    async def _bg():
        try:
            await job_runner.run_export(req.clip_id, opts)
        except Exception:  # state (export_failed + export_error) is persisted by run_export
            pass

    job_runner.spawn(_bg())
    return {"clip_id": clip.id, "status": "exporting", "status_url": f"/api/clips/{clip.id}"}


@router.post("/export/batch")
async def export_selected_batch(req: BatchExportRequest, db: AsyncSession = Depends(get_db)):
    """Render all selected clips (or specified clip_ids) for a job with the chosen layout and subtitles."""
    job = await db.get(Job, req.job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    if req.clip_ids:
        clips = (await db.execute(select(Clip).where(Clip.job_id == req.job_id, Clip.id.in_(req.clip_ids)))).scalars().all()
    else:
        clips = (await db.execute(select(Clip).where(Clip.job_id == req.job_id, Clip.status == "selected"))).scalars().all()
    if not clips:
        raise HTTPException(status_code=404, detail="No selected clips found for this job")

    opts = req.model_dump(exclude={"job_id", "clip_ids"}, exclude_none=True)
    rendered = []
    for c in clips:
        try:
            res = await job_runner.run_export(c.id, opts)
            rendered.append({
                "clip_id": c.id,
                "status": "exported",
                "duration": res["duration"],
                "resolution": res["resolution"],
                "codec": res.get("codec", "h264"),
                "audio_codec": res.get("audio_codec", "aac"),
                "encoder_used": res["sync_report"]["encoder"],
                "gpu_accelerated": res.get("gpu_accelerated", False),
                "file_size_mb": res["size_mb"],
                "download_url": res["export_url"],
                "export_url": res["export_url"],
                "sync_report": res["sync_report"],
            })
        except Exception as exc:
            rendered.append({"clip_id": c.id, "status": "export_failed", "error": str(exc)})
    return {"job_id": req.job_id, "exports": rendered}
