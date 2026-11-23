from pydantic import BaseModel, ConfigDict
from typing import Optional, List, Dict, Any
import datetime

class ClipBase(BaseModel):
    start_time: float
    end_time: float
    duration: float
    score: float = 90.0
    reason: str = ""
    category: str = "hype"
    suggested_title: str = "Viral Short"
    title_suggestions: List[str] = []
    suggested_description: str = ""
    hashtags: List[str] = []
    thumbnail_text: str = ""
    thumbnail_timestamp: float = 0.0
    layout: str = "facecam_gameplay"
    facecam_crop: Optional[Dict[str, Any]] = None
    gameplay_crop: Optional[Dict[str, Any]] = None
    subtitle_style: Optional[Dict[str, Any]] = None

class ClipUpdate(BaseModel):
    start_time: Optional[float] = None
    end_time: Optional[float] = None
    suggested_title: Optional[str] = None
    title_suggestions: Optional[List[str]] = None
    suggested_description: Optional[str] = None
    hashtags: Optional[List[str]] = None
    thumbnail_text: Optional[str] = None
    thumbnail_timestamp: Optional[float] = None
    layout: Optional[str] = None
    facecam_crop: Optional[Dict[str, Any]] = None
    gameplay_crop: Optional[Dict[str, Any]] = None
    subtitle_style: Optional[Dict[str, Any]] = None
    status: Optional[str] = None

class ClipMetadataRequest(BaseModel):
    gemini_api_key: Optional[str] = None
    openai_api_key: Optional[str] = None
    use_ai_api: bool = True

class ClipTranslateRequest(BaseModel):
    target_language: str
    gemini_api_key: Optional[str] = None
    openai_api_key: Optional[str] = None

class ClipExportRequest(BaseModel):
    title: Optional[str] = None
    start_time: Optional[float] = None
    end_time: Optional[float] = None
    resolution: Optional[str] = "1080x1920"
    layout: Optional[str] = None
    facecam_crop: Optional[Dict[str, Any]] = None
    gameplay_crop: Optional[Dict[str, Any]] = None
    subtitle_style: Optional[Dict[str, Any]] = None
    burn_subtitles: Optional[bool] = True
    prefer_hardware: Optional[bool] = True
    fps: Optional[int] = 30
    bitrate_kbps: Optional[int] = None
    quality: Optional[str] = "balanced"
    audio_bitrate_kbps: Optional[int] = 160

class TranscriptWordCorrection(BaseModel):
    word: str
    start: float
    end: float
    probability: Optional[float] = 1.0

class TranscriptSegmentCorrection(BaseModel):
    id: Optional[str] = None
    start: Optional[float] = None
    end: Optional[float] = None
    text: str
    words: Optional[List[TranscriptWordCorrection]] = None

class ClipTranscriptUpdate(BaseModel):
    segments: List[TranscriptSegmentCorrection]

class ClipResponse(ClipBase):
    id: str
    job_id: str
    status: str
    export_path: Optional[str] = None
    export_url: Optional[str] = None
    file_size_mb: float = 0.0
    sync_report: Optional[Dict[str, Any]] = None
    created_at: datetime.datetime

    model_config = ConfigDict(from_attributes=True)
