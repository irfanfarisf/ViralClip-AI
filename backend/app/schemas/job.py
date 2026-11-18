from pydantic import BaseModel, ConfigDict
from typing import Optional, List, Dict, Any
import datetime
from backend.app.schemas.clip import ClipResponse
from backend.app.schemas.video import VideoResponse

class TranscriptWordSchema(BaseModel):
    word: str
    start: float
    end: float
    probability: float

class TranscriptSegmentResponse(BaseModel):
    id: str
    start_time: float
    end_time: float
    text: str
    confidence: float
    words: List[Dict[str, Any]] = []

    model_config = ConfigDict(from_attributes=True)

class JobCreate(BaseModel):
    video_id: str
    settings: Optional[Dict[str, Any]] = None

class JobResponse(BaseModel):
    id: str
    video_id: str
    status: str
    progress: int
    current_stage: str
    last_completed_stage: Optional[str] = None
    error_message: Optional[str] = None
    encoder_used: Optional[str] = None
    detected_language: Optional[str] = None
    detected_language_probability: Optional[float] = None
    whisper_model: Optional[str] = None
    settings: Dict[str, Any] = {}
    created_at: datetime.datetime
    updated_at: datetime.datetime
    video: Optional[VideoResponse] = None
    clips: List[ClipResponse] = []
    transcripts: List[TranscriptSegmentResponse] = []

    model_config = ConfigDict(from_attributes=True)
