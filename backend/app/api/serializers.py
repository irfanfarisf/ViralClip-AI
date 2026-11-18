from backend.app.models.clip import Clip


def clip_to_dict(c: Clip) -> dict:
    sr = c.sync_report or {}
    dl_url = c.export_url if c.status == "exported" else None
    return {
        "id": c.id,
        "job_id": c.job_id,
        "title": c.suggested_title,
        "suggested_title": c.suggested_title,
        "title_suggestions": c.title_suggestions or [],
        "description": c.suggested_description,
        "suggested_description": c.suggested_description,
        "transcript_excerpt": c.suggested_description,
        "selected": c.status == "selected",
        "start_time": c.start_time,
        "end_time": c.end_time,
        "duration": c.duration,
        "score": c.score,
        "reason": c.reason,
        "category": c.category,
        "layout": c.layout,
        "status": c.status,
        "tags": c.hashtags or [],
        "hashtags": c.hashtags or [],
        "thumbnail_text": c.thumbnail_text or "",
        "thumbnail_timestamp": c.thumbnail_timestamp or round(c.start_time + c.duration * 0.42, 2),
        "facecam_crop": c.facecam_crop,
        "gameplay_crop": c.gameplay_crop,
        "subtitle_style": c.subtitle_style,
        "export_url": dl_url,
        "download_url": dl_url,
        "export_progress": c.export_progress or 0,
        "export_error": c.export_error,
        "file_size_mb": c.file_size_mb,
        "resolution": sr.get("resolution") if c.status == "exported" else None,
        "codec": sr.get("codec") if c.status == "exported" else None,
        "audio_codec": sr.get("audio_codec") if c.status == "exported" else None,
        "encoder_used": sr.get("encoder") if c.status == "exported" else None,
        "gpu_accelerated": bool(sr.get("gpu_accelerated")) if c.status == "exported" else False,
        "sync_report": c.sync_report or None,
    }
