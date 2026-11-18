import datetime
import uuid
from sqlalchemy import String, Float, Integer, DateTime, ForeignKey, JSON
from sqlalchemy.orm import Mapped, mapped_column, relationship
from backend.app.database import Base

class Clip(Base):
    __tablename__ = "clips"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=lambda: f"clip_{uuid.uuid4().hex[:12]}")
    job_id: Mapped[str] = mapped_column(String, ForeignKey("jobs.id", ondelete="CASCADE"), nullable=False)
    start_time: Mapped[float] = mapped_column(Float, nullable=False)
    end_time: Mapped[float] = mapped_column(Float, nullable=False)
    duration: Mapped[float] = mapped_column(Float, nullable=False)
    score: Mapped[float] = mapped_column(Float, default=90.0) # 0 to 100
    reason: Mapped[str] = mapped_column(String, default="High engagement moment")
    category: Mapped[str] = mapped_column(String, default="hype")
    suggested_title: Mapped[str] = mapped_column(String, default="Viral Short")
    title_suggestions: Mapped[list] = mapped_column(JSON, default=list)
    suggested_description: Mapped[str] = mapped_column(String, default="")
    hashtags: Mapped[list] = mapped_column(JSON, default=list)
    thumbnail_text: Mapped[str] = mapped_column(String, default="")
    thumbnail_timestamp: Mapped[float] = mapped_column(Float, default=0.0)
    layout: Mapped[str] = mapped_column(String, default="facecam_gameplay")
    facecam_crop: Mapped[dict] = mapped_column(JSON, default=dict)
    gameplay_crop: Mapped[dict] = mapped_column(JSON, default=dict)
    subtitle_style: Mapped[dict] = mapped_column(JSON, default=dict)
    status: Mapped[str] = mapped_column(String, default="detected") # detected, selected, rejected, exporting, exported, export_failed
    export_path: Mapped[str] = mapped_column(String, nullable=True)
    export_url: Mapped[str] = mapped_column(String, nullable=True)
    file_size_mb: Mapped[float] = mapped_column(Float, default=0.0)
    sync_report: Mapped[dict] = mapped_column(JSON, default=dict)
    export_progress: Mapped[int] = mapped_column(Integer, default=0)
    export_error: Mapped[str] = mapped_column(String, nullable=True)
    created_at: Mapped[datetime.datetime] = mapped_column(DateTime, default=lambda: datetime.datetime.now(datetime.timezone.utc))

    job = relationship("Job", back_populates="clips")
