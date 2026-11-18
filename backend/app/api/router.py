from fastapi import APIRouter
from backend.app.api.health import router as health_router
from backend.app.api.videos import router as videos_router
from backend.app.api.jobs import router as jobs_router
from backend.app.api.exports import router as exports_router
from backend.app.api.pipeline import router as pipeline_router

api_router = APIRouter(prefix="/api")
api_router.include_router(health_router)
api_router.include_router(pipeline_router)
api_router.include_router(videos_router)
api_router.include_router(jobs_router)
api_router.include_router(exports_router)
