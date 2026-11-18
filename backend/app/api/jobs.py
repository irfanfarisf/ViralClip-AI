"""Job endpoints: list/detail/start/cancel/delete, progress WebSocket, legacy per-job clip export."""
from typing import List

from fastapi import APIRouter, Depends, HTTPException, Query, WebSocket, WebSocketDisconnect
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from backend.app import job_runner, video_processor as vp
from backend.app.api.serializers import clip_to_dict
from backend.app.api.videos import create_job as create_job_row, purge_video
from backend.app.config import settings
from backend.app.database import get_db
from backend.app.export import ExportError
from backend.app.models.clip import Clip
from backend.app.models.job import Job
from backend.app.models.transcript import TranscriptSegment
from backend.app.models.video import Video
from backend.app.schemas.clip import ClipExportRequest
from backend.app.schemas.job import JobCreate

router = APIRouter(prefix="/jobs", tags=["Jobs"])

active_websockets = job_runner.active_websockets


async def _job(db: AsyncSession, id: str, with_rel: bool = True) -> Job:
    q = select(Job).where(Job.id == id)
    if with_rel:
        q = q.options(selectinload(Job.video), selectinload(Job.clips))
    job = (await db.execute(q)).scalar_one_or_none()
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    return job


@router.post("", response_model=dict)
async def create_job(req: JobCreate, db: AsyncSession = Depends(get_db)):
    if not (await db.execute(select(Video.id).where(Video.id == req.video_id))).scalar_one_or_none():
        raise HTTPException(status_code=404, detail="Video not found")
    job = await create_job_row(db, req.video_id, req.settings)
    return {"id": job.id, "status": job.status, "message": "Job created and processing queued"}


@router.get("", response_model=List[dict])
async def list_jobs(db: AsyncSession = Depends(get_db)):
    clip_count_subq = (
        select(func.count(Clip.id))
        .where(Clip.job_id == Job.id)
        .scalar_subquery()
    )
    stmt = (
        select(Job, clip_count_subq.label("clips_count"))
        .options(selectinload(Job.video))
        .order_by(Job.created_at.desc())
    )
    rows = (await db.execute(stmt)).all()
    out = []
    for j, count in rows:
        opts = j.settings or {}
        out.append({
            "id": j.id,
            "video_id": j.video_id,
            "title": j.video.filename if j.video else "Untitled",
            "source_type": j.video.source_type if j.video else "local",
            "status": j.status,
            "import_state": opts.get("import_state", j.status.upper()),
            "progress": j.progress,
            "current_stage": j.current_stage,
            "error_message": j.error_message,
            "detected_language": getattr(j, "detected_language", None) or opts.get("detected_language"),
            "duration": j.video.duration if j.video else 0.0,
            "width": j.video.width if j.video else 0,
            "height": j.video.height if j.video else 0,
            "fps": j.video.fps if j.video else 0.0,
            "file_size_mb": j.video.file_size_mb if j.video else 0.0,
            "bytes_transferred": opts.get("bytes_transferred", 0),
            "total_bytes": opts.get("total_bytes"),
            "speed_bps": opts.get("speed_bps", 0.0),
            "eta_seconds": opts.get("eta_seconds"),
            "can_resume": bool(opts.get("can_resume", False)),
            "video_url": f"/api/videos/{j.video_id}/stream" if j.video else None,
            "clips_count": int(count or 0),
            "created_at": j.created_at.isoformat(),
        })
    return out


@router.get("/{id}")
async def get_job(id: str, include_words: bool = Query(False), db: AsyncSession = Depends(get_db)):
    job = await _job(db, id)
    transcripts = (await db.execute(
        select(TranscriptSegment).where(TranscriptSegment.video_id == job.video_id)
        .order_by(TranscriptSegment.start_time))).scalars().all()
    v = job.video
    opts = job.settings or {}
    return {
        "id": job.id,
        "video_id": job.video_id,
        "status": job.status,
        "import_state": opts.get("import_state", job.status.upper()),
        "progress": job.progress,
        "current_stage": job.current_stage,
        "last_completed_stage": job.last_completed_stage,
        "error_message": job.error_message,
        "encoder_used": job.encoder_used,
        "detected_language": getattr(job, "detected_language", None) or opts.get("detected_language"),
        "detected_language_probability": opts.get("detected_language_probability"),
        "whisper_model": opts.get("whisper_model") or "base",
        "whisper_device": opts.get("whisper_device"),
        "transcribed_seconds": opts.get("transcribed_seconds", 0.0),
        "total_audio_seconds": opts.get("total_audio_seconds", v.duration if v else 0.0),
        "realtime_factor": opts.get("realtime_factor", 0.0),
        "warnings": opts.get("warnings", []),
        "bytes_transferred": opts.get("bytes_transferred", 0),
        "total_bytes": opts.get("total_bytes"),
        "speed_bps": opts.get("speed_bps", 0.0),
        "eta_seconds": opts.get("eta_seconds"),
        "chunks_received": opts.get("chunks_received", 0),
        "total_chunks": opts.get("total_chunks", 0),
        "can_resume": bool(opts.get("can_resume", False)),
        "created_at": job.created_at.isoformat(),
        "updated_at": job.updated_at.isoformat(),
        "video": {
            "id": v.id,
            "filename": v.filename,
            "source_type": v.source_type,
            "duration": v.duration,
            "width": v.width,
            "height": v.height,
            "fps": v.fps,
            "file_size_mb": v.file_size_mb,
            "has_audio": bool(v.audio_codec),
            "video_url": f"/api/videos/{v.id}/stream",
        } if v else None,
        "clips": [clip_to_dict(c) for c in sorted(job.clips, key=lambda c: -c.score)],
        "transcripts": [{"id": t.id, "start": t.start_time, "end": t.end_time, "text": t.text,
                         "confidence": t.confidence, "words": t.words if include_words else []} for t in transcripts],
    }


@router.post("/{id}/start")
@router.post("/{id}/retry")
async def start_job(id: str, db: AsyncSession = Depends(get_db)):
    job = await _job(db, id, with_rel=True)
    if job_runner.is_running(id):
        raise HTTPException(status_code=409, detail="Job is already running")
    job_runner.cancelled.discard(id)
    opts = dict(job.settings or {})
    source_url = opts.get("source_url") or (job.video.original_url if job.video else None)
    from pathlib import Path
    has_source_file = bool(job.video and job.video.file_path and Path(job.video.file_path).exists())
    if source_url and not has_source_file:
        job.status, job.progress, job.current_stage, job.error_message = "QUEUED", 0, "QUEUED: Retrying stream download", None
        opts["import_state"] = "QUEUED"
        job.settings = opts
        await db.commit()
        job_runner.start_url_import(job.id, source_url)
        return {"message": "Import retry started", "status": "QUEUED"}

    job.status, job.progress, job.current_stage, job.error_message = "queued", 0, "Queued for analysis", None
    await db.commit()
    job_runner.start_pipeline(job.id)
    return {"message": "Job started", "status": "queued"}


@router.post("/{id}/cancel")
async def cancel_job(id: str, db: AsyncSession = Depends(get_db)):
    job = await _job(db, id, with_rel=False)
    if job.status not in job_runner.ACTIVE_STATUSES:
        raise HTTPException(status_code=409, detail=f"Job is not running (status: {job.status})")
    job_runner.cancelled.add(id)
    opts = dict(job.settings or {})
    upload_id = opts.get("upload_id")
    if upload_id:
        import asyncio
        from backend.app import video_import as vi
        await asyncio.to_thread(vi.cancel_chunked_upload, upload_id)
    was_upper = job.status.isupper()
    new_status = "CANCELLED" if was_upper else "cancelled"
    job.status, job.current_stage = new_status, "CANCELLED: Cancelled by user" if was_upper else "Cancelling..."
    opts["import_state"] = "CANCELLED"
    opts["can_resume"] = False
    job.settings = opts
    await db.commit()
    await job_runner.broadcast(id, {
        "job_id": id,
        "status": new_status,
        "import_state": "CANCELLED",
        "progress": job.progress,
        "stage": job.current_stage,
    })
    return {"message": "Job cancelled", "status": new_status}


@router.delete("/{id}")
async def delete_job(id: str, db: AsyncSession = Depends(get_db)):
    job = await _job(db, id, with_rel=False)
    if job.status in job_runner.ACTIVE_STATUSES:
        job_runner.cancelled.add(id)
    video = (await db.execute(select(Video).where(Video.id == job.video_id))).scalar_one_or_none()
    if video:
        await purge_video(db, video)  # cascades to jobs/clips and removes files
    else:
        await db.delete(job)
        await db.commit()
    return {"message": "Job, source video and exports deleted"}


@router.post("/{job_id}/clips/{clip_id}/export")
async def export_clip(job_id: str, clip_id: str, req: ClipExportRequest, db: AsyncSession = Depends(get_db)):
    """Render synchronously (progress is also pushed over WebSocket under the clip id)."""
    clip = (await db.execute(select(Clip).where(Clip.id == clip_id, Clip.job_id == job_id))).scalar_one_or_none()
    if not clip:
        raise HTTPException(status_code=404, detail="Clip not found for this job")
    if req.layout is not None and req.layout not in vp.LAYOUTS:
        raise HTTPException(status_code=422, detail=f"Unknown layout '{req.layout}'. Choose from {', '.join(vp.LAYOUTS)}")
    opts = {k: v for k, v in {
        "title": req.title, "start_time": req.start_time, "end_time": req.end_time,
        "layout": req.layout,
        "facecam_crop": req.facecam_crop, "gameplay_crop": req.gameplay_crop,
        "subtitle_style": req.subtitle_style, "prefer_hardware": req.prefer_hardware,
        "fps": req.fps, "bitrate_kbps": req.bitrate_kbps,
        "quality": req.quality, "audio_bitrate_kbps": req.audio_bitrate_kbps}.items() if v is not None}
    try:
        res = await job_runner.run_export(clip_id, opts)
    except ExportError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    await db.refresh(clip)
    return {
        "id": clip_id,
        "title": clip.suggested_title,
        "description": clip.suggested_description,
        "hashtags": clip.hashtags or [],
        "title_suggestions": clip.title_suggestions or [],
        "thumbnail_text": clip.thumbnail_text or "",
        "thumbnail_timestamp": clip.thumbnail_timestamp or round(clip.start_time + clip.duration * 0.42, 2),
        "status": "exported",
        "export_url": res["export_url"],
        "download_url": res["export_url"],
        "duration": res["duration"],
        "resolution": res["resolution"],
        "codec": res.get("codec", "h264"),
        "audio_codec": res.get("audio_codec", "aac"),
        "encoder": res["sync_report"]["encoder"],
        "encoder_used": res["sync_report"]["encoder"],
        "gpu_accelerated": res.get("gpu_accelerated", False),
        "file_size_mb": res["size_mb"],
        "sync_report": res["sync_report"],
    }


@router.websocket("/ws/{id}")
async def websocket_progress(websocket: WebSocket, id: str):
    """Progress stream for a job id or a clip id (export)."""
    origin = websocket.headers.get("origin")
    allowed = set(getattr(settings, "CORS_ORIGINS", []))
    if origin and allowed and "*" not in allowed and origin not in allowed:
        await websocket.close(code=1008)
        return

    await websocket.accept()
    active_websockets.setdefault(id, []).append(websocket)
    try:
        while True:
            await websocket.receive_text()
    except WebSocketDisconnect:
        pass
    finally:
        conns = active_websockets.get(id, [])
        if websocket in conns:
            conns.remove(websocket)
        if not conns:
            active_websockets.pop(id, None)
