import datetime
import uuid
from sqlalchemy import String, Float, Integer, Boolean, DateTime
from sqlalchemy.orm import Mapped, mapped_column, relationship
from backend.app.database import Base

class Video(Base):
    __tablename__ = "videos"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=lambda: f"vid_{uuid.uuid4().hex[:12]}")
    filename: Mapped[str] = mapped_column(String, nullable=False)
    original_url: Mapped[str] = mapped_column(String, nullable=True)
    source_type: Mapped[str] = mapped_column(String, default="local") # local, youtube, twitch
    file_path: Mapped[str] = mapped_column(String, nullable=False)
    file_size_mb: Mapped[float] = mapped_column(Float, default=0.0)
    duration: Mapped[float] = mapped_column(Float, default=0.0)
    width: Mapped[int] = mapped_column(Integer, default=1920)
    height: Mapped[int] = mapped_column(Integer, default=1080)
    fps: Mapped[float] = mapped_column(Float, default=30.0)
    is_vfr: Mapped[bool] = mapped_column(Boolean, default=False)
    codec: Mapped[str] = mapped_column(String, default="h264")
    audio_codec: Mapped[str] = mapped_column(String, default="aac")
    status: Mapped[str] = mapped_column(String, default="ready") # uploading, ready, error
    error_message: Mapped[str] = mapped_column(String, nullable=True)
    created_at: Mapped[datetime.datetime] = mapped_column(DateTime, default=lambda: datetime.datetime.now(datetime.timezone.utc))

    jobs = relationship("Job", back_populates="video", cascade="all, delete-orphan")
    transcripts = relationship("TranscriptSegment", back_populates="video", cascade="all, delete-orphan")
