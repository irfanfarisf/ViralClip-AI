import asyncio
import atexit
import os
import shutil
import subprocess
import tempfile
from pathlib import Path

import pytest

_SESSION_TMP = Path(tempfile.mkdtemp(prefix="vc_pytest_session_"))
atexit.register(lambda: shutil.rmtree(_SESSION_TMP, ignore_errors=True))

os.environ["STORAGE_DIR"] = str(_SESSION_TMP / "storage")
os.environ["TEMP_DIR"] = str(_SESSION_TMP / "storage" / "temp")
os.environ["OUTPUT_DIR"] = str(_SESSION_TMP / "storage" / "output")
os.environ["DB_PATH"] = str(_SESSION_TMP / "storage" / "db" / "test.db")

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine  # noqa: E402

from backend.app import cleanup, database, job_runner, main  # noqa: E402
from backend.app.config import settings  # noqa: E402
from backend.app.gpu_config import find_ffmpeg  # noqa: E402

_CACHED_MP4_BYTES: bytes | None = None


def build_tiny_mp4_bytes() -> bytes:
    """Generate a real 2-second MP4 with FFmpeg (testsrc2 + sine), cached for the test session."""
    global _CACHED_MP4_BYTES
    if _CACHED_MP4_BYTES is not None:
        return _CACHED_MP4_BYTES
    ff = find_ffmpeg()
    if not ff:
        pytest.skip("FFmpeg is not installed; skipping real MP4 upload test")
    out = _SESSION_TMP / "fixture_tiny_2s.mp4"
    if not out.exists():
        out.parent.mkdir(parents=True, exist_ok=True)
        subprocess.run(
            [
                ff, "-y", "-loglevel", "error",
                "-f", "lavfi", "-i", "testsrc2=s=320x240:r=15:d=2",
                "-f", "lavfi", "-i", "sine=frequency=440:sample_rate=16000:duration=2",
                "-map", "0:v:0", "-map", "1:a:0",
                "-c:v", "libx264", "-preset", "ultrafast", "-pix_fmt", "yuv420p",
                "-c:a", "aac", "-b:a", "64k", "-shortest",
                str(out),
            ],
            check=True,
            timeout=30,
        )
    _CACHED_MP4_BYTES = out.read_bytes()
    return _CACHED_MP4_BYTES


@pytest.fixture(scope="session")
def sample_mp4_bytes() -> bytes:
    return build_tiny_mp4_bytes()


@pytest.fixture(autouse=True)
def isolated_db_and_storage(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """Point settings and SQLAlchemy engine/sessionmaker at an isolated temp directory for every test."""
    storage_dir = tmp_path / "storage"
    temp_dir = storage_dir / "temp"
    output_dir = storage_dir / "output"
    db_dir = storage_dir / "db"
    for d in (storage_dir, temp_dir, output_dir, db_dir):
        d.mkdir(parents=True, exist_ok=True)
    db_path = db_dir / "test_viralclip.db"

    monkeypatch.setattr(settings, "STORAGE_DIR", str(storage_dir))
    monkeypatch.setattr(settings, "TEMP_DIR", str(temp_dir))
    monkeypatch.setattr(settings, "OUTPUT_DIR", str(output_dir))
    monkeypatch.setattr(settings, "DB_PATH", str(db_path))

    db_url = f"sqlite+aiosqlite:///{db_path.as_posix()}"
    test_engine = create_async_engine(db_url, echo=False, future=True)
    if hasattr(database, "_register_sqlite_pragmas"):
        database._register_sqlite_pragmas(test_engine)
    test_session_maker = async_sessionmaker(test_engine, class_=AsyncSession, expire_on_commit=False)

    monkeypatch.setattr(database, "DATABASE_URL", db_url)
    monkeypatch.setattr(database, "engine", test_engine)
    monkeypatch.setattr(database, "async_session_maker", test_session_maker)
    monkeypatch.setattr(job_runner, "engine", test_engine)
    monkeypatch.setattr(job_runner, "async_session_maker", test_session_maker)
    monkeypatch.setattr(cleanup, "async_session_maker", test_session_maker)
    monkeypatch.setattr(main, "engine", test_engine)

    job_runner.cancelled.clear()
    if hasattr(job_runner, "active_url_imports"):
        job_runner.active_url_imports.clear()
    job_runner._heavy = None
    job_runner._import_sem_inst = None
    if hasattr(job_runner, "_export_sem_inst"):
        job_runner._export_sem_inst = None

    yield

    try:
        asyncio.run(test_engine.dispose())
    except RuntimeError:
        pass
