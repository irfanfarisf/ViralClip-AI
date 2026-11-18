import asyncio
import shutil
import sys

from fastapi import APIRouter

from backend.app import gpu_config
from backend.app.cleanup import cleanup_storage
from backend.app.config import settings
from backend.app.transcription import detect_whisper_hardware, whisper_available

router = APIRouter(prefix="/health", tags=["Health"])


@router.post("/cleanup")
async def trigger_safe_cleanup():
    """Safely remove orphaned temp directories, _work scratch files, and incomplete .part.mp4 renders.
    Never deletes user videos registered in the database or exported MP4 clips.
    """
    removed = await cleanup_storage()
    return {"status": "ok", "removed": removed}


@router.get("")
async def get_health():
    """Everything here is detected at request time (encoders are probed once, then cached)."""
    enc = await asyncio.to_thread(gpu_config.detect_encoders)
    selected = enc.get("selected")
    return {
        "status": "ok",
        "online": True,
        "ffmpeg": bool(enc["ffmpeg"]),
        "ffprobe": bool(enc["ffprobe"]),
        "ffmpeg_version": enc.get("version"),
        "gpu_encoder": selected["label"] if selected else None,
        "encoder_kind": selected["kind"] if selected else None,
        "hardware_encoders": [e["name"] for e in enc["working"]],
        "encoder_vendors": enc.get("vendors", {}),
        "whisper": whisper_available(),
        "whisper_model": settings.WHISPER_MODEL,
        "whisper_hardware": detect_whisper_hardware(),
        "yt_dlp": bool(shutil.which("yt-dlp")) or _has_module("yt_dlp"),
        "python_version": sys.version.split()[0],
        "storage_free_gb": round(shutil.disk_usage(settings.STORAGE_DIR).free / 1024 ** 3, 1),
    }


def _has_module(name: str) -> bool:
    import importlib.util
    return importlib.util.find_spec(name) is not None
