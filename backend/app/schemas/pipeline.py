from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field, field_validator, model_validator

from backend.app.video_processor import LAYOUTS


class AnalyzeRequest(BaseModel):
    video_id: str
    language: Optional[str] = Field(None, description="ISO code, e.g. 'en'. Auto-detect when omitted or set to 'auto'.")
    whisper_model: Optional[str] = Field(None, description="Whisper model, e.g. 'tiny', 'base', 'small', 'medium'. Defaults to server setting.")
    transcribe: bool = True
    min_clip_seconds: float = Field(20, ge=5, le=120)
    max_clip_seconds: float = Field(45, ge=5, le=180)
    target_clip_seconds: float = Field(30, ge=5, le=120)
    max_clips: int = Field(5, ge=1, le=20)
    gemini_api_key: Optional[str] = None
    openai_api_key: Optional[str] = None
    use_ai_api: bool = True

    @model_validator(mode="after")
    def _range(self):
        if self.min_clip_seconds > self.max_clip_seconds:
            raise ValueError("min_clip_seconds must be <= max_clip_seconds")
        return self


class GenerateClipsRequest(BaseModel):
    job_id: str
    min_clip_seconds: float = Field(20, ge=5, le=120)
    max_clip_seconds: float = Field(45, ge=5, le=180)
    target_clip_seconds: float = Field(30, ge=5, le=120)
    max_clips: int = Field(5, ge=1, le=20)
    gemini_api_key: Optional[str] = None
    openai_api_key: Optional[str] = None
    use_ai_api: bool = True

    @model_validator(mode="after")
    def _range(self):
        if self.min_clip_seconds > self.max_clip_seconds:
            raise ValueError("min_clip_seconds must be <= max_clip_seconds")
        return self


class ExportRequest(BaseModel):
    clip_id: str
    title: Optional[str] = Field(None, max_length=120)
    layout: str = "facecam_gameplay"
    facecam_crop: Optional[Dict[str, Any]] = None
    gameplay_crop: Optional[Dict[str, Any]] = None
    subtitle_style: Optional[Dict[str, Any]] = None
    burn_subtitles: bool = True
    prefer_hardware: bool = True
    preferred_encoder: Optional[str] = None
    fps: int = Field(30, ge=15, le=60)
    bitrate_kbps: Optional[int] = Field(None, ge=500, le=50000)
    quality: str = Field("balanced", description="high | balanced | fast")
    audio_bitrate_kbps: int = Field(160, ge=64, le=320)
    start_time: Optional[float] = Field(None, ge=0)
    end_time: Optional[float] = Field(None, gt=0)

    @field_validator("layout")
    @classmethod
    def _layout(cls, v: str) -> str:
        if v not in LAYOUTS:
            raise ValueError(f"layout must be one of {', '.join(LAYOUTS)}")
        return v


class BatchExportRequest(BaseModel):
    job_id: str
    clip_ids: Optional[List[str]] = None
    layout: str = "facecam_gameplay"
    facecam_crop: Optional[Dict[str, Any]] = None
    gameplay_crop: Optional[Dict[str, Any]] = None
    subtitle_style: Optional[Dict[str, Any]] = None
    burn_subtitles: bool = True
    prefer_hardware: bool = True
    fps: int = Field(30, ge=15, le=60)
    bitrate_kbps: Optional[int] = Field(None, ge=500, le=50000)
    quality: str = "balanced"

    @field_validator("layout")
    @classmethod
    def _layout(cls, v: str) -> str:
        if v not in LAYOUTS:
            raise ValueError(f"layout must be one of {', '.join(LAYOUTS)}")
        return v
