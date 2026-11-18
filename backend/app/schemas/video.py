import datetime
from typing import Optional
from pydantic import BaseModel, ConfigDict, Field


class VideoBase(BaseModel):
    filename: str
    source_type: str = "local"
    original_url: Optional[str] = None
    duration: float = 0.0
    width: int = 1920
    height: int = 1080
    fps: float = 30.0
    file_size_mb: float = 0.0


class VideoCreate(BaseModel):
    filename: str
    source_type: str = "local"
    original_url: Optional[str] = None


class ChunkedUploadInitRequest(BaseModel):
    filename: str
    total_bytes: int = Field(..., gt=0)
    chunk_size: int = Field(8 * 1024 * 1024, gt=0)
    fingerprint: Optional[str] = None
    file_sha256: Optional[str] = None
    auto_analyze: bool = False
    language: Optional[str] = None
    whisper_model: Optional[str] = None
    gemini_api_key: Optional[str] = None
    openai_api_key: Optional[str] = None


class ChunkedUploadCompleteRequest(BaseModel):
    file_sha256: Optional[str] = None
    auto_analyze: Optional[bool] = None


class VideoImportUrlRequest(BaseModel):
    url: str
    platform: str = "youtube"
    background: bool = True
    auto_analyze: bool = False
    language: Optional[str] = None
    whisper_model: Optional[str] = None
    gemini_api_key: Optional[str] = None
    openai_api_key: Optional[str] = None


class VideoResponse(VideoBase):
    id: str
    status: str
    error_message: Optional[str] = None
    created_at: datetime.datetime

    model_config = ConfigDict(from_attributes=True)
