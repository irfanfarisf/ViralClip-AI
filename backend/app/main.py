import asyncio
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from backend.app import job_runner
from backend.app.api.router import api_router
from backend.app.cleanup import cleanup_storage
from backend.app.config import ensure_dirs, settings
from backend.app.database import Base, engine
import backend.app.models as _models  # register models with Base
_ = _models

log = logging.getLogger("viralclip")


async def _cleanup_loop():
    while True:
        try:
            await cleanup_storage()
        except Exception:  # noqa: BLE001
            log.exception("cleanup failed")
        await asyncio.sleep(settings.CLEANUP_INTERVAL_MINUTES * 60)


@asynccontextmanager
async def lifespan(app: FastAPI):
    ensure_dirs()
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    await job_runner.migrate_schema()
    recovered = await job_runner.recover_interrupted()
    if recovered["jobs"] or recovered["clips"]:
        log.warning("Marked interrupted work as failed: %s", recovered)
    cleaner = asyncio.create_task(_cleanup_loop())
    yield
    cleaner.cancel()
    await engine.dispose()


app = FastAPI(
    title="ViralClip AI API",
    version="1.0.0",
    description="Converts authorized videos into vertical short-form clips (Whisper + FFmpeg).",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(api_router)


@app.get("/")
async def root():
    return {"name": "ViralClip AI Backend", "version": app.version, "status": "online", "docs": "/docs"}
