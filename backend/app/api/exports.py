from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.api.serializers import clip_to_dict
from backend.app.database import get_db
from backend.app.job_runner import safe_filename
from backend.app.models.clip import Clip

router = APIRouter(prefix="/exports", tags=["Exports"])


@router.get("")
async def list_exports(db: AsyncSession = Depends(get_db)):
    """Return all exported clips ordered newest first for Export History."""
    clips = (await db.execute(
        select(Clip).where(Clip.status == "exported").order_by(Clip.created_at.desc())
    )).scalars().all()
    return [clip_to_dict(c) for c in clips]


async def _exported_clip(db: AsyncSession, id: str) -> Clip:
    clip = (await db.execute(select(Clip).where(Clip.id == id))).scalar_one_or_none()
    if not clip:
        raise HTTPException(status_code=404, detail="Clip not found")
    if clip.status != "exported" or not clip.export_path:
        raise HTTPException(status_code=404, detail="This clip has not been exported yet")
    return clip


@router.get("/{id}/download")
async def download_export(id: str, db: AsyncSession = Depends(get_db)):
    """Serve the rendered MP4 only; never falls back to the source video."""
    clip = await _exported_clip(db, id)
    if not Path(clip.export_path).exists():
        raise HTTPException(status_code=410, detail="The rendered file is no longer on disk; export again")
    return FileResponse(clip.export_path, media_type="video/mp4", filename=safe_filename(clip.suggested_title, clip.id))


@router.get("/{id}/sync-report")
async def get_sync_report(id: str, db: AsyncSession = Depends(get_db)):
    clip = await _exported_clip(db, id)
    return clip.sync_report
