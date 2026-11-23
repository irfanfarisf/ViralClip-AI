"""Safe cleanup of leftovers. Never touches a video that has a database row or an exported file."""
import shutil
import time
from pathlib import Path

from sqlalchemy import select

from backend.app.config import settings
from backend.app.database import async_session_maker
from backend.app.models.video import Video

ORPHAN_MIN_AGE_S = 3600  # an upload dir exists briefly before its DB row; never race it


def _age(p: Path) -> float:
    return time.time() - p.stat().st_mtime


async def cleanup_storage(min_age_s: float = ORPHAN_MIN_AGE_S) -> dict:
    """Remove only orphaned temp dirs, stale _work scratch dirs, and incomplete .part.mp4/render_* dirs.
    Never deletes user videos registered in the database or completed .mp4 exports.
    """
    removed = {"orphan_dirs": 0, "work_dirs": 0, "partial_files": 0}
    async with async_session_maker() as s:
        known = set((await s.execute(select(Video.id))).scalars().all())
    temp = Path(settings.TEMP_DIR)
    if temp.exists():
        for d in temp.iterdir():
            if not d.is_dir():
                continue
            if d.name not in known and _age(d) >= min_age_s:
                shutil.rmtree(d, ignore_errors=True)
                removed["orphan_dirs"] += 1
                continue
            work = d / "_work"
            if work.exists() and _age(work) >= min_age_s:
                shutil.rmtree(work, ignore_errors=True)
                removed["work_dirs"] += 1
            for part_up in d.glob("*.uploading.part"):
                if _age(part_up) >= min_age_s:
                    part_up.unlink(missing_ok=True)
                    (d / "upload_session.json").unlink(missing_ok=True)
                    removed["partial_files"] += 1
            for ytdl_part in list(d.glob("*.part*")) + list(d.glob("*.ytdl")):
                if ytdl_part.name.endswith(".uploading.part"):
                    continue
                if _age(ytdl_part) >= min_age_s:
                    ytdl_part.unlink(missing_ok=True)
                    removed["partial_files"] += 1
    out = Path(settings.OUTPUT_DIR)
    if out.exists():
        for p in out.rglob("*.part.mp4"):
            if _age(p) >= min_age_s:
                p.unlink(missing_ok=True)
                removed["partial_files"] += 1
        for d in out.rglob("render_*"):
            if d.is_dir() and _age(d) >= min_age_s:
                shutil.rmtree(d, ignore_errors=True)
                removed["work_dirs"] += 1
    return removed
