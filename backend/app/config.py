from pathlib import Path
from typing import List

from pydantic import model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

PROJECT_ROOT = Path(__file__).resolve().parents[2]


def _resolve_path(p: str | Path) -> str:
    path = Path(p)
    if not path.is_absolute():
        path = PROJECT_ROOT / path
    return str(path.resolve())


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=str(PROJECT_ROOT / ".env"),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    HOST: str = "127.0.0.1"
    PORT: int = 8000
    DEBUG: bool = True
    CORS_ORIGINS: List[str] = ["http://localhost:5173", "http://127.0.0.1:5173"]

    STORAGE_DIR: str = "./storage"
    TEMP_DIR: str = "./storage/temp"
    OUTPUT_DIR: str = "./storage/output"
    DB_PATH: str = "./storage/db/viralclip.db"

    MAX_UPLOAD_SIZE_GB: int = 4
    MAX_VIDEO_DURATION_HOURS: int = 4
    UPLOAD_CHUNK_SIZE_MB: int = 16

    YTDLP_CONCURRENT_FRAGMENTS: int = 4
    YTDLP_SOCKET_TIMEOUT: int = 20
    YTDLP_HTTP_CHUNK_SIZE_MB: int = 10
    YTDLP_RETRIES: int = 5
    YTDLP_FRAGMENT_RETRIES: int = 5
    YTDLP_MAX_DOWNLOAD_SECONDS: int = 14400
    YTDLP_STALL_TIMEOUT_SECONDS: int = 90

    FFMPEG_PATH: str = ""
    FFPROBE_PATH: str = ""

    WHISPER_MODEL: str = "base"
    WHISPER_PROFILE: str = "balanced"
    WHISPER_DEVICE: str = "auto"
    WHISPER_COMPUTE_TYPE: str = "auto"
    WHISPER_CPU_THREADS: int = 0
    WHISPER_BEAM_SIZE: int = 1
    WHISPER_CHUNK_SECONDS: int = 600

    MAX_CONCURRENT_IMPORTS: int = 1
    MAX_CONCURRENT_TRANSCRIPTIONS: int = 1
    MAX_CONCURRENT_EXPORTS: int = 1

    GEMINI_API_KEY: str = ""
    OPENAI_API_KEY: str = ""

    TEMP_FILE_TTL_HOURS: int = 24
    CLEANUP_INTERVAL_MINUTES: int = 30

    @model_validator(mode="after")
    def _anchor_paths(self) -> "Settings":
        self.STORAGE_DIR = _resolve_path(self.STORAGE_DIR)
        self.TEMP_DIR = _resolve_path(self.TEMP_DIR)
        self.OUTPUT_DIR = _resolve_path(self.OUTPUT_DIR)
        self.DB_PATH = _resolve_path(self.DB_PATH)
        return self


settings = Settings()


def ensure_dirs() -> None:
    Path(settings.STORAGE_DIR).mkdir(parents=True, exist_ok=True)
    Path(settings.TEMP_DIR).mkdir(parents=True, exist_ok=True)
    Path(settings.OUTPUT_DIR).mkdir(parents=True, exist_ok=True)
    Path(settings.DB_PATH).parent.mkdir(parents=True, exist_ok=True)
