"""High-performance video import engine:
- Streaming & resumable chunked local uploads (3+ hour / multi-GB videos, constant RAM)
- Per-chunk & final SHA-256 / byte-size integrity verification and chunk deduplication
- Temporary .uploading.part files with atomic os.replace() finalization
- Pre-flight free disk space checks (HTTP 507 on insufficient storage)
- Fast header-only FFprobe metadata extraction (no full-video decoding)
- Background-ready yt-dlp streaming downloads with real-time progress hooks (speed, bytes, total, ETA),
  resumable .part support, retry handling, cancellation, and zero transcoding.
"""
from __future__ import annotations

import hashlib
import json
import os
import queue
import re
import shutil
import signal
import subprocess
import sys
import threading
import time
import uuid
from dataclasses import dataclass, asdict
from fractions import Fraction
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple
from urllib.parse import parse_qs, urlparse

from backend.app.config import settings
from backend.app.gpu_config import find_ffmpeg, find_ffprobe

ALLOWED_EXTENSIONS = {".mp4", ".mov", ".mkv", ".webm", ".avi"}
CHUNK = 4 * 1024 * 1024          # 4 MB streaming write block
SUB_CHUNK = 256 * 1024            # 256 KB network read block (constant low RAM)
DEFAULT_UPLOAD_CHUNK_SIZE = max(1, int(getattr(settings, "UPLOAD_CHUNK_SIZE_MB", 16) or 16)) * 1024 * 1024  # 16 MB default resumable slice
MIN_FREE_DISK_BYTES = 500 * 1024 * 1024      # 500 MB safety reserve

YOUTUBE_HOSTS = {"youtube.com", "www.youtube.com", "m.youtube.com", "youtu.be"}
TWITCH_HOSTS = {"twitch.tv", "www.twitch.tv", "m.twitch.tv", "clips.twitch.tv"}

_upload_locks: Dict[str, threading.Lock] = {}
_session_cache: Dict[str, dict] = {}
_locks_guard = threading.Lock()
_active_download_procs: Dict[str, subprocess.Popen] = {}
_procs_guard = threading.Lock()


def _kill_process_tree(proc: subprocess.Popen) -> None:
    """Terminate a subprocess and all its children (e.g. yt-dlp + child ffmpeg) without leaving orphans."""
    if proc.poll() is not None:
        return
    try:
        if os.name == "nt":
            subprocess.run(
                ["taskkill", "/T", "/F", "/PID", str(proc.pid)],
                capture_output=True,
                timeout=10,
            )
        else:
            os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
    except Exception:
        try:
            proc.kill()
        except Exception:
            pass


def terminate_download_process(job_id: str) -> bool:
    """Immediately terminate any active external download subprocess for `job_id`."""
    with _procs_guard:
        proc = _active_download_procs.get(job_id)
    if proc is not None:
        _kill_process_tree(proc)
        return True
    return False


def terminate_all_download_processes() -> None:
    """Terminate all active download subprocesses (called on backend shutdown)."""
    with _procs_guard:
        procs = list(_active_download_procs.values())
    for proc in procs:
        _kill_process_tree(proc)


def _get_upload_lock(upload_id: str) -> threading.Lock:
    with _locks_guard:
        if upload_id not in _upload_locks:
            _upload_locks[upload_id] = threading.Lock()
        return _upload_locks[upload_id]


class ImportFailure(Exception):
    """Raised for user-facing import problems. `status` is the suggested HTTP status."""

    def __init__(self, message: str, status: int = 400):
        super().__init__(message)
        self.message = message
        self.status = status


@dataclass
class VideoMetadata:
    duration: float
    width: int
    height: int
    fps: float
    codec: str
    audio_codec: Optional[str]
    has_audio: bool
    is_vfr: bool
    file_size_mb: float
    file_size_bytes: int = 0
    rotation: int = 0

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class ImportProgress:
    stage: str                      # QUEUED, INITIALIZING, UPLOADING, DOWNLOADING, VALIDATING, EXTRACTING_METADATA, COMPLETED, FAILED, CANCELLED
    progress: int                   # 0..100
    bytes_transferred: int = 0
    total_bytes: Optional[int] = None
    speed_bps: float = 0.0
    eta_seconds: Optional[float] = None
    chunks_received: int = 0
    total_chunks: int = 0
    message: str = ""

    def to_dict(self) -> dict:
        return asdict(self)


def check_disk_space(required_bytes: int = 0) -> int:
    """Verify sufficient free disk space in STORAGE_DIR. Returns free bytes or raises ImportFailure(507)."""
    storage_root = Path(settings.STORAGE_DIR)
    storage_root.mkdir(parents=True, exist_ok=True)
    free_bytes = shutil.disk_usage(storage_root).free
    needed = max(0, int(required_bytes)) + MIN_FREE_DISK_BYTES
    if free_bytes < needed:
        free_gb = free_bytes / (1024 ** 3)
        req_gb = needed / (1024 ** 3)
        raise ImportFailure(
            f"Insufficient disk space: {free_gb:.2f} GB free, at least {req_gb:.2f} GB required (including 500 MB reserve).",
            status=507,
        )
    return free_bytes


def storage_dir_for(video_id: str) -> Path:
    d = Path(settings.TEMP_DIR) / video_id
    d.mkdir(parents=True, exist_ok=True)
    return d


def new_video_id() -> str:
    return f"vid_{uuid.uuid4().hex[:12]}"


def safe_display_name(name: Optional[str], fallback: str = "video") -> str:
    base = Path(name or fallback).name
    base = re.sub(r"[^\w.\- ()\[\]]", "_", base).strip(" .") or fallback
    return base[:150]


def validate_extension(filename: Optional[str]) -> str:
    ext = Path(filename or "").suffix.lower()
    if ext not in ALLOWED_EXTENSIONS:
        raise ImportFailure(
            f"Unsupported file type '{ext or 'none'}'. Allowed: {', '.join(sorted(ALLOWED_EXTENSIONS))}"
        )
    return ext


def validate_size_limit(total_bytes: int) -> None:
    if total_bytes <= 0:
        raise ImportFailure("The uploaded file is empty.", 400)
    max_bytes = int(settings.MAX_UPLOAD_SIZE_GB * (1024 ** 3))
    if total_bytes > max_bytes:
        raise ImportFailure(f"File exceeds the {settings.MAX_UPLOAD_SIZE_GB} GB upload limit.", 413)


def _parse_rate(value: str) -> float:
    try:
        f = Fraction(value)
        return float(f) if f.denominator else 0.0
    except (ValueError, ZeroDivisionError):
        return 0.0


def probe_video(path: Path) -> VideoMetadata:
    """Fast header-only FFprobe metadata extraction (avoids full-video decoding on 3-4h files)."""
    ffprobe = find_ffprobe()
    if not ffprobe:
        raise ImportFailure(
            "FFprobe is not installed, so the video cannot be validated. "
            "Install FFmpeg (or set FFPROBE_PATH) and retry.", 503
        )
    if not path.exists() or path.stat().st_size == 0:
        raise ImportFailure("The uploaded file is empty or missing on disk.", 400)
    try:
        proc = subprocess.run(
            [
                ffprobe,
                "-v", "error",
                "-analyzeduration", "20M",
                "-probesize", "20M",
                "-print_format", "json",
                "-show_format",
                "-show_streams",
                str(path),
            ],
            capture_output=True,
            text=True,
            timeout=60,
        )
    except subprocess.TimeoutExpired:
        raise ImportFailure("Timed out while reading the video metadata.")
    if proc.returncode != 0:
        raise ImportFailure("The file is not a readable video (ffprobe could not parse it).")
    try:
        data = json.loads(proc.stdout or "{}")
    except json.JSONDecodeError:
        raise ImportFailure("ffprobe returned unreadable output.", 500)

    streams = data.get("streams", [])
    video = next(
        (s for s in streams if s.get("codec_type") == "video" and not s.get("disposition", {}).get("attached_pic")),
        None,
    )
    if not video:
        raise ImportFailure("The file contains no video stream.")
    audio_streams = [s for s in streams if s.get("codec_type") == "audio"]
    audio = next((s for s in audio_streams if s.get("disposition", {}).get("default")), None) or (
        audio_streams[0] if audio_streams else None
    )

    fmt = data.get("format", {})
    try:
        duration = float(video.get("duration") or fmt.get("duration") or 0)
    except ValueError:
        duration = 0.0
    if duration <= 0:
        raise ImportFailure("Could not determine the video duration.")
    max_s = settings.MAX_VIDEO_DURATION_HOURS * 3600
    if duration > max_s:
        raise ImportFailure(f"Video is longer than the {settings.MAX_VIDEO_DURATION_HOURS} h limit.")

    width, height = int(video.get("width", 0)), int(video.get("height", 0))
    if width < 2 or height < 2:
        raise ImportFailure("Video has invalid dimensions.")
    rotation = 0
    for sd in video.get("side_data_list", []) or []:
        if "rotation" in sd:
            rotation = int(sd["rotation"]) % 360
    if rotation in (90, 270):
        width, height = height, width

    r_fps = _parse_rate(video.get("r_frame_rate", "0/1"))
    avg_fps = _parse_rate(video.get("avg_frame_rate", "0/1"))
    fps = avg_fps or r_fps or 30.0
    is_vfr = bool(r_fps and avg_fps and abs(r_fps - avg_fps) / r_fps > 0.02)

    size_bytes = path.stat().st_size
    return VideoMetadata(
        duration=round(duration, 3),
        width=width,
        height=height,
        fps=round(fps, 3),
        codec=video.get("codec_name", "unknown"),
        audio_codec=audio.get("codec_name") if audio else None,
        has_audio=audio is not None,
        is_vfr=is_vfr,
        file_size_mb=round(size_bytes / 1048576, 2),
        file_size_bytes=size_bytes,
        rotation=rotation,
    )


async def save_upload(
    upload,
    dest: Path,
    *,
    expected_bytes: Optional[int] = None,
    progress_cb: Optional[Callable[[int, float], None]] = None,
    should_cancel: Optional[Callable[[], bool]] = None,
) -> int:
    """Stream an UploadFile directly to `dest.uploading.part` and atomically rename to `dest`.
    Never loads full video into RAM. Cleans up temporary file on failure or cancellation.
    """
    max_bytes = int(settings.MAX_UPLOAD_SIZE_GB * (1024 ** 3))
    check_disk_space(expected_bytes or 0)
    part = dest.with_suffix(dest.suffix + ".uploading.part")
    total = 0
    t0 = time.perf_counter()
    try:
        with open(part, "wb") as out:
            while True:
                if should_cancel and should_cancel():
                    raise ImportFailure("Upload cancelled by user.", 499)
                chunk = await upload.read(CHUNK)
                if not chunk:
                    break
                total += len(chunk)
                if total > max_bytes:
                    raise ImportFailure(f"File exceeds the {settings.MAX_UPLOAD_SIZE_GB} GB upload limit.", 413)
                out.write(chunk)
                if progress_cb:
                    elapsed = max(time.perf_counter() - t0, 0.001)
                    progress_cb(total, total / elapsed)
    except BaseException:
        part.unlink(missing_ok=True)
        dest.unlink(missing_ok=True)
        raise
    if total == 0:
        part.unlink(missing_ok=True)
        raise ImportFailure("The uploaded file is empty.")
    if expected_bytes is not None and total != expected_bytes:
        part.unlink(missing_ok=True)
        raise ImportFailure(f"Incomplete upload: received {total} of {expected_bytes} bytes.", 422)
    os.replace(part, dest)
    return total


def ingest_local(upload_filename: Optional[str], dest_dir: Path, ext: str) -> Tuple[Path, VideoMetadata]:
    """Probe an already-saved upload; delete the directory if it is not a valid video."""
    path = dest_dir / f"source{ext}"
    try:
        return path, probe_video(path)
    except BaseException:
        shutil.rmtree(dest_dir, ignore_errors=True)
        raise


# ------------------------------------------------------------------ Resumable Chunked Upload Engine

def _session_meta_path(video_id: str) -> Path:
    return Path(settings.TEMP_DIR) / video_id / "upload_session.json"


def find_resumable_session(fingerprint: str) -> Optional[dict]:
    """Find an existing incomplete chunked upload matching `fingerprint`."""
    if not fingerprint:
        return None
    temp_root = Path(settings.TEMP_DIR)
    if not temp_root.exists():
        return None
    for meta_file in temp_root.glob("vid_*/upload_session.json"):
        try:
            data = json.loads(meta_file.read_text(encoding="utf-8"))
            if data.get("fingerprint") == fingerprint and data.get("status") in ("INITIALIZING", "UPLOADING", "FAILED"):
                part_path = Path(data.get("part_path", ""))
                if part_path.exists():
                    return data
        except Exception:
            continue
    return None


def init_chunked_upload(
    filename: str,
    total_bytes: int,
    chunk_size: int = DEFAULT_UPLOAD_CHUNK_SIZE,
    fingerprint: Optional[str] = None,
    file_sha256: Optional[str] = None,
    video_id: Optional[str] = None,
    job_id: Optional[str] = None,
    auto_analyze: bool = False,
    options: Optional[dict] = None,
) -> dict:
    """Initialize or resume a chunked upload session on disk."""
    ext = validate_extension(filename)
    validate_size_limit(total_bytes)
    check_disk_space(total_bytes)

    if fingerprint:
        existing = find_resumable_session(fingerprint)
        if existing:
            return {**existing, "resumed": True}

    vid_id = video_id or new_video_id()
    j_id = job_id or f"job_{uuid.uuid4().hex[:12]}"
    dest_dir = storage_dir_for(vid_id)
    part_path = dest_dir / f"source{ext}.uploading.part"
    final_path = dest_dir / f"source{ext}"

    chunk_sz = max(256 * 1024, min(int(chunk_size or DEFAULT_UPLOAD_CHUNK_SIZE), 64 * 1024 * 1024))
    total_chunks = max(1, (total_bytes + chunk_sz - 1) // chunk_sz)

    # Create empty temporary .uploading.part file if not present
    if not part_path.exists():
        part_path.touch()

    now = time.time()
    session = {
        "upload_id": vid_id,
        "video_id": vid_id,
        "job_id": j_id,
        "filename": safe_display_name(filename),
        "ext": ext,
        "total_bytes": int(total_bytes),
        "chunk_size": chunk_sz,
        "total_chunks": total_chunks,
        "file_sha256": file_sha256 or None,
        "fingerprint": fingerprint or f"{safe_display_name(filename)}:{total_bytes}",
        "part_path": str(part_path),
        "final_path": str(final_path),
        "received_chunks": {},  # str(chunk_index) -> {"offset": int, "size": int, "sha256": str}
        "bytes_received": 0,
        "started_at": now,
        "updated_at": now,
        "status": "UPLOADING",
        "auto_analyze": bool(auto_analyze),
        "options": options or {},
        "resumed": False,
    }
    _session_meta_path(vid_id).write_text(json.dumps(session), encoding="utf-8")
    with _get_upload_lock(vid_id):
        _session_cache[vid_id] = {**session, "_meta_path": str(_session_meta_path(vid_id))}
    return session


def get_upload_session(upload_id: str) -> dict:
    meta_file = _session_meta_path(upload_id)
    cached = _session_cache.get(upload_id)
    if cached and cached.get("_meta_path") == str(meta_file) and meta_file.exists():
        return cached
    if not meta_file.exists():
        _session_cache.pop(upload_id, None)
        raise ImportFailure("Upload session not found or already finalized.", 404)
    try:
        loaded = json.loads(meta_file.read_text(encoding="utf-8"))
        _session_cache[upload_id] = {**loaded, "_meta_path": str(meta_file)}
        return _session_cache[upload_id]
    except Exception as exc:
        raise ImportFailure(f"Corrupt upload session state: {exc}", 500)


def write_upload_chunk(
    upload_id: str,
    chunk_index: int,
    data: bytes,
    offset: Optional[int] = None,
    expected_sha256: Optional[str] = None,
    should_cancel: Optional[Callable[[], bool]] = None,
) -> dict:
    """Verify, deduplicate, and write a single chunk directly to the temporary .uploading.part file."""
    if should_cancel and should_cancel():
        raise ImportFailure("Upload cancelled by user.", 499)

    chunk_len = len(data)
    if chunk_len == 0:
        raise ImportFailure("Chunk payload is empty.", 400)

    # Compute SHA-256 outside the per-upload lock so pipelined chunks hash in parallel
    actual_sha256 = hashlib.sha256(data).hexdigest()
    if expected_sha256 and actual_sha256.lower() != expected_sha256.strip().lower():
        raise ImportFailure(
            f"Chunk {chunk_index} SHA-256 checksum mismatch (expected {expected_sha256[:12]}..., got {actual_sha256[:12]}...).",
            422,
        )

    lock = _get_upload_lock(upload_id)
    with lock:
        session = get_upload_session(upload_id)
        if session.get("status") == "CANCELLED":
            raise ImportFailure("Upload session was cancelled.", 499)

        total_chunks = int(session["total_chunks"])
        total_bytes = int(session["total_bytes"])
        chunk_sz = int(session["chunk_size"])
        if not (0 <= chunk_index < total_chunks):
            raise ImportFailure(f"Invalid chunk_index {chunk_index} (expected 0..{total_chunks - 1}).", 422)

        calc_offset = int(offset) if offset is not None else chunk_index * chunk_sz
        if calc_offset < 0 or calc_offset + chunk_len > total_bytes:
            raise ImportFailure(
                f"Chunk range {calc_offset}..{calc_offset + chunk_len} exceeds total file size ({total_bytes} bytes).",
                422,
            )

        key = str(chunk_index)
        received = session.get("received_chunks", {})
        # Prevent duplicate chunk writes if this exact chunk was already verified
        if key in received and received[key].get("sha256") == actual_sha256 and received[key].get("size") == chunk_len:
            duplicate = True
        else:
            duplicate = False
            part_path = Path(session["part_path"])
            if not part_path.exists():
                part_path.parent.mkdir(parents=True, exist_ok=True)
                part_path.touch()
            with open(part_path, "r+b") as f:
                f.seek(calc_offset)
                f.write(data)

            received[key] = {
                "offset": calc_offset,
                "size": chunk_len,
                "sha256": actual_sha256,
            }
            session["received_chunks"] = received

        bytes_received = sum(int(c["size"]) for c in received.values())
        now = time.time()
        elapsed = max(now - float(session.get("started_at", now)), 0.001)
        speed_bps = bytes_received / elapsed
        remaining_bytes = max(0, total_bytes - bytes_received)
        eta_seconds = round(remaining_bytes / speed_bps, 2) if speed_bps > 0 else None
        pct = min(99, int((bytes_received / max(total_bytes, 1)) * 100))

        session["bytes_received"] = bytes_received
        session["updated_at"] = now
        session["status"] = "UPLOADING"
        disk_payload = {k: v for k, v in session.items() if k != "_meta_path"}
        _session_meta_path(upload_id).write_text(json.dumps(disk_payload), encoding="utf-8")

        return {
            "upload_id": upload_id,
            "video_id": session["video_id"],
            "job_id": session["job_id"],
            "chunk_index": chunk_index,
            "duplicate": duplicate,
            "chunk_sha256": actual_sha256,
            "bytes_received": bytes_received,
            "total_bytes": total_bytes,
            "chunks_received": len(received),
            "total_chunks": total_chunks,
            "progress": pct,
            "speed_bps": round(speed_bps, 1),
            "eta_seconds": eta_seconds,
            "stage": "UPLOADING",
        }


def verify_file_sha256(path: Path, expected_sha256: str) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        while True:
            blk = f.read(8 * 1024 * 1024)
            if not blk:
                break
            h.update(blk)
    digest = h.hexdigest()
    if digest.lower() != expected_sha256.strip().lower():
        raise ImportFailure(
            f"Final file SHA-256 integrity check failed (expected {expected_sha256[:12]}..., got {digest[:12]}...).",
            422,
        )
    return digest


def finalize_chunked_upload(
    upload_id: str,
    expected_sha256: Optional[str] = None,
    on_stage: Optional[Callable[[str, int, str], None]] = None,
) -> Tuple[Path, VideoMetadata, dict]:
    """Verify all chunks and final file integrity, atomically rename .part -> source.<ext>, and probe metadata."""
    lock = _get_upload_lock(upload_id)
    with lock:
        session = get_upload_session(upload_id)
        if session.get("status") == "CANCELLED":
            raise ImportFailure("Upload session was cancelled.", 499)

        if on_stage:
            on_stage("VALIDATING", 92, "Validating uploaded chunks and file integrity")

        total_chunks = int(session["total_chunks"])
        total_bytes = int(session["total_bytes"])
        received = session.get("received_chunks", {})
        missing = [i for i in range(total_chunks) if str(i) not in received]
        if missing:
            raise ImportFailure(
                f"Cannot finalize upload: missing {len(missing)} chunk(s) (first missing: #{missing[0]}).",
                422,
            )

        part_path = Path(session["part_path"])
        final_path = Path(session["final_path"])
        if not part_path.exists():
            raise ImportFailure("Temporary upload file is missing on disk.", 404)

        actual_size = part_path.stat().st_size
        if actual_size != total_bytes:
            raise ImportFailure(
                f"Final file size mismatch: expected {total_bytes} bytes, found {actual_size} bytes on disk.",
                422,
            )

        sha_to_check = expected_sha256 or session.get("file_sha256")
        if sha_to_check:
            verify_file_sha256(part_path, sha_to_check)

        # Atomically finalize temporary file without copying bytes
        os.replace(part_path, final_path)

        if on_stage:
            on_stage("EXTRACTING_METADATA", 96, "Extracting video metadata with FFprobe")

        try:
            meta = probe_video(final_path)
        except BaseException:
            shutil.rmtree(final_path.parent, ignore_errors=True)
            _session_cache.pop(upload_id, None)
            _upload_locks.pop(upload_id, None)
            raise

        # Remove upload session state file now that source.<ext> is finalized and verified
        _session_meta_path(upload_id).unlink(missing_ok=True)
        _session_cache.pop(upload_id, None)
        _upload_locks.pop(upload_id, None)
        return final_path, meta, {k: v for k, v in session.items() if k != "_meta_path"}


def cancel_chunked_upload(upload_id: str) -> dict:
    """Cancel an in-progress chunked upload and remove its temporary .uploading.part file."""
    lock = _get_upload_lock(upload_id)
    with lock:
        meta_file = _session_meta_path(upload_id)
        session = {}
        if meta_file.exists():
            try:
                session = json.loads(meta_file.read_text(encoding="utf-8"))
                session["status"] = "CANCELLED"
            except Exception:
                pass
        dest_dir = Path(settings.TEMP_DIR) / upload_id
        for p in dest_dir.glob("*.uploading.part"):
            p.unlink(missing_ok=True)
        meta_file.unlink(missing_ok=True)
        if dest_dir.exists() and not any(dest_dir.iterdir()):
            shutil.rmtree(dest_dir, ignore_errors=True)
        _session_cache.pop(upload_id, None)
        _upload_locks.pop(upload_id, None)
        return {"upload_id": upload_id, "status": "CANCELLED", "job_id": session.get("job_id")}


# ---------------------------------------------------------------- external import (YouTube / Twitch)

def normalize_url(url: str) -> str:
    """Canonicalize supported YouTube/Twitch URLs so equivalent links deduplicate reliably."""
    raw = (url or "").strip()
    try:
        parsed = urlparse(raw)
    except ValueError:
        return raw
    host = (parsed.hostname or "").lower()
    path = parsed.path or ""
    if host in YOUTUBE_HOSTS:
        qs = parse_qs(parsed.query)
        vid_id = None
        if host == "youtu.be":
            vid_id = path.strip("/").split("/")[0] or None
        elif path.startswith("/watch") and qs.get("v"):
            vid_id = qs["v"][0]
        elif path.startswith(("/shorts/", "/live/", "/embed/")):
            parts = [p for p in path.split("/") if p]
            if len(parts) >= 2:
                vid_id = parts[1]
        if vid_id:
            return f"youtube:{vid_id}"
    if host in TWITCH_HOSTS:
        parts = [p for p in path.split("/") if p]
        if len(parts) >= 2 and parts[0] == "videos":
            return f"twitch:video:{parts[1]}"
        if host == "clips.twitch.tv" and parts:
            return f"twitch:clip:{parts[0]}"
    return raw


def classify_url(url: str) -> str:
    """Return 'youtube' | 'twitch' or raise ImportFailure."""
    try:
        parsed = urlparse(url.strip())
    except ValueError:
        raise ImportFailure("Invalid URL.")
    if parsed.scheme not in ("http", "https") or not parsed.hostname:
        raise ImportFailure("URL must start with http:// or https://")
    host = parsed.hostname.lower()
    if host in YOUTUBE_HOSTS:
        return "youtube"
    if host in TWITCH_HOSTS:
        return "twitch"
    raise ImportFailure("Only YouTube and Twitch URLs are supported for import.")


def _ytdlp_command() -> Optional[list]:
    exe = shutil.which("yt-dlp")
    if exe:
        return [exe]
    if sys.modules.get("yt_dlp") is not None:
        return [sys.executable, "-m", "yt_dlp"]
    import importlib.util
    try:
        if importlib.util.find_spec("yt_dlp") is not None:
            return [sys.executable, "-m", "yt_dlp"]
    except ValueError:
        return None
    return None


def ytdlp_available() -> bool:
    return _ytdlp_command() is not None


_PROGRESS_RE = re.compile(r"VC_PROG\|([^|]*)\|([^|]*)\|([^|]*)\|([^|]*)\|([^|\s]*)")


def _parse_opt_float(val: str) -> Optional[float]:
    try:
        v = float(val)
        return v if v >= 0 else None
    except (ValueError, TypeError):
        return None


def _cleanup_partial_downloads(dest_dir: Path) -> None:
    if not dest_dir.exists():
        return
    for p in list(dest_dir.glob("*.part*")) + list(dest_dir.glob("*.ytdl")):
        p.unlink(missing_ok=True)


def _select_downloaded_file(dest_dir: Path, expected_path: Optional[Path] = None) -> Optional[Path]:
    if expected_path and expected_path.exists() and expected_path.suffix.lower() in ALLOWED_EXTENSIONS:
        return expected_path
    # Prefer final merged file (exclude intermediate unmerged format streams like source.f137.mp4)
    cands = [
        p for p in dest_dir.glob("source.*")
        if p.suffix.lower() in ALLOWED_EXTENSIONS
        and not p.name.endswith(".part")
        and not re.match(r"^source\.f\d+\.", p.name)
    ]
    if cands:
        return max(cands, key=lambda p: p.stat().st_size)
    fallback = [
        p for p in dest_dir.glob("source.*")
        if p.suffix.lower() in ALLOWED_EXTENSIONS and not p.name.endswith(".part")
    ]
    return max(fallback, key=lambda p: p.stat().st_size) if fallback else None


def import_external(
    url: str,
    dest_dir: Path,
    *,
    progress_cb: Optional[Callable[[ImportProgress], None]] = None,
    should_cancel: Optional[Callable[[], bool]] = None,
    keep_partial_on_error: bool = False,
    concurrent_fragments: Optional[int] = None,
    job_id: Optional[str] = None,
) -> Tuple[Path, VideoMetadata, str, str]:
    """Download a public YouTube/Twitch video the user is authorized to use via yt-dlp.

    - Extracts metadata once (single round-trip) and reuses it for download when supported.
    - Prefers H.264 MP4+M4A (or single-stream progressive MP4 when FFmpeg is absent) with zero video re-encoding.
    - Configures HTTP chunk sizing, fragment concurrency, retries, and stall/wall-clock timeouts.
    - Emits monotonic progress (bytes_transferred, total_bytes, speed_bps, eta_seconds) and muxing stage updates.
    - Supports immediate mid-download/mid-muxing cancellation without leaving orphan subprocesses.
    """
    platform = classify_url(url)
    check_disk_space(0)
    cmd = _ytdlp_command()
    if not cmd:
        if not keep_partial_on_error:
            shutil.rmtree(dest_dir, ignore_errors=True)
        raise ImportFailure(
            "yt-dlp is not installed on the server, so URL import is unavailable. "
            "Upload the video file instead, or install yt-dlp.",
            503,
        )

    ff = find_ffmpeg()
    ff_dir = str(Path(ff).parent) if ff else None
    out_tpl = str(dest_dir / "source.%(ext)s")
    frag_N = max(1, min(int(concurrent_fragments or getattr(settings, "YTDLP_CONCURRENT_FRAGMENTS", 4) or 4), 16))
    sock_timeout = max(5, int(getattr(settings, "YTDLP_SOCKET_TIMEOUT", 20) or 20))
    http_chunk_mb = max(1, min(int(getattr(settings, "YTDLP_HTTP_CHUNK_SIZE_MB", 10) or 10), 64))
    http_chunk_bytes = http_chunk_mb * 1024 * 1024
    retries = max(1, int(getattr(settings, "YTDLP_RETRIES", 5) or 5))
    frag_retries = max(1, int(getattr(settings, "YTDLP_FRAGMENT_RETRIES", 5) or 5))
    max_dl_sec = max(60, int(getattr(settings, "YTDLP_MAX_DOWNLOAD_SECONDS", 14400) or 14400))
    stall_timeout = max(15, int(getattr(settings, "YTDLP_STALL_TIMEOUT_SECONDS", 90) or 90))

    if ff_dir:
        fmt_sel = (
            "bv*[ext=mp4][vcodec^=avc1][height<=1080]+ba[ext=m4a]/"
            "bv*[ext=mp4][height<=1080]+ba[ext=m4a]/"
            "b[ext=mp4][height<=1080]/"
            "bv*[height<=1080]+ba/b[height<=1080]/b"
        )
    else:
        fmt_sel = "b[ext=mp4][height<=1080]/b[height<=1080]/b"

    if progress_cb:
        progress_cb(ImportProgress(
            stage="INITIALIZING",
            progress=2,
            message=f"Connecting to {platform.title()} and extracting video metadata...",
        ))

    title = f"{platform} video"
    expected_final: Optional[Path] = None

    # Prefer native Python yt_dlp module for single-pass extract + progress_hooks + postprocessor_hooks
    try:
        import yt_dlp as _ytdlp_mod
        has_py_ytdlp = True
    except ImportError:
        has_py_ytdlp = False

    if has_py_ytdlp:
        hook_lock = threading.Lock()
        dl_state = {
            "stream_idx": 0,
            "last_filename": None,
            "high_pct": 5,
            "total_streams": 1,
            "last_bytes": 0,
            "last_activity": time.monotonic(),
            "started_at": time.monotonic(),
        }

        def _check_abort() -> None:
            if should_cancel and should_cancel():
                raise ImportFailure("Download cancelled by user.", 499)
            now = time.monotonic()
            if (now - dl_state["started_at"]) > max_dl_sec:
                raise ImportFailure("Download exceeded maximum allowed duration.", 504)
            if (now - dl_state["last_activity"]) > stall_timeout:
                raise ImportFailure("Download stalled (no data received before timeout).", 504)

        def _hook(d: dict) -> None:
            _check_abort()
            st = d.get("status")
            fname = d.get("filename") or d.get("tmpfilename")
            with hook_lock:
                dl_b = int(d.get("downloaded_bytes") or 0)
                if dl_b > dl_state["last_bytes"] or st == "finished":
                    dl_state["last_activity"] = time.monotonic()
                    dl_state["last_bytes"] = dl_b
                if fname and fname != dl_state["last_filename"]:
                    if dl_state["last_filename"] is not None:
                        dl_state["stream_idx"] += 1
                    dl_state["last_filename"] = fname
                    dl_state["last_bytes"] = dl_b

                tot_streams = max(1, dl_state["total_streams"])
                s_idx = min(dl_state["stream_idx"], tot_streams - 1)
                # Partition 5..90 monotonically across video (5..78) + audio (78..90) when 2 streams exist
                if tot_streams >= 2:
                    band_start, band_end = (5, 78) if s_idx == 0 else (78, 90)
                else:
                    band_start, band_end = 5, 90

                if st == "downloading" and progress_cb:
                    tot_raw = d.get("total_bytes") or d.get("total_bytes_estimate")
                    tot_int = int(tot_raw) if tot_raw else None
                    spd = float(d.get("speed") or 0.0)
                    eta_raw = d.get("eta")
                    eta_val = round(float(eta_raw), 1) if eta_raw is not None else None
                    frag_idx = int(d.get("fragment_index") or 0)
                    frag_cnt = int(d.get("fragment_count") or 0)
                    if tot_int and tot_int > 0:
                        frac = min(max(dl_b / tot_int, 0.0), 1.0)
                    elif frag_cnt > 0:
                        frac = min(max(frag_idx / frag_cnt, 0.0), 1.0)
                    else:
                        frac = 0.25
                    raw_pct = band_start + int(frac * (band_end - band_start))
                    pct = max(dl_state["high_pct"], min(band_end, raw_pct))
                    dl_state["high_pct"] = pct
                    stream_lbl = "audio stream" if (tot_streams >= 2 and s_idx > 0) else "video stream"
                    progress_cb(ImportProgress(
                        stage="DOWNLOADING",
                        progress=pct,
                        bytes_transferred=dl_b,
                        total_bytes=tot_int,
                        speed_bps=round(spd, 1),
                        eta_seconds=eta_val,
                        chunks_received=frag_idx,
                        total_chunks=frag_cnt,
                        message=f"Downloading {stream_lbl} for '{title}' from {platform.title()}",
                    ))
                elif st == "finished" and progress_cb:
                    pct = max(dl_state["high_pct"], band_end)
                    dl_state["high_pct"] = pct
                    dl_b_fin = int(d.get("downloaded_bytes") or d.get("total_bytes") or 0)
                    progress_cb(ImportProgress(
                        stage="DOWNLOADING",
                        progress=pct,
                        bytes_transferred=dl_b_fin,
                        total_bytes=dl_b_fin or None,
                        speed_bps=0.0,
                        eta_seconds=0.0 if pct >= 90 else None,
                        message="Stream downloaded; preparing container..." if pct >= 90 else "Video stream complete; downloading audio...",
                    ))

        def _pp_hook(d: dict) -> None:
            if should_cancel and should_cancel():
                raise ImportFailure("Download cancelled by user.", 499)
            if d.get("status") == "started" and progress_cb:
                progress_cb(ImportProgress(
                    stage="VALIDATING",
                    progress=91,
                    message="Muxing audio & video streams (stream copy, no re-encoding)...",
                ))

        ydl_opts: Dict[str, Any] = {
            "format": fmt_sel,
            "merge_output_format": "mp4" if ff_dir else None,
            "outtmpl": out_tpl,
            "noplaylist": True,
            "continuedl": True,
            "nopart": False,
            "retries": retries,
            "fragment_retries": frag_retries,
            "extractor_retries": 3,
            "file_access_retries": 5,
            "concurrent_fragment_downloads": frag_N,
            "http_chunk_size": http_chunk_bytes,
            "buffersize": 65536,
            "socket_timeout": sock_timeout,
            "quiet": True,
            "no_warnings": True,
            "progress_hooks": [_hook],
            "postprocessor_hooks": [_pp_hook],
        }
        if not ff_dir:
            ydl_opts.pop("merge_output_format", None)
        else:
            ydl_opts["ffmpeg_location"] = ff_dir

        try:
            with _ytdlp_mod.YoutubeDL(ydl_opts) as ydl:
                if should_cancel and should_cancel():
                    raise ImportFailure("Download cancelled by user.", 499)
                info = ydl.extract_info(url, download=False, process=True)
                if not info:
                    raise ImportFailure("Could not resolve video metadata from URL.", 422)
                title = str(info.get("title") or title)
                dur_est = float(info.get("duration") or 0.0)
                max_s = settings.MAX_VIDEO_DURATION_HOURS * 3600
                if dur_est > max_s:
                    raise ImportFailure(f"Video duration ({dur_est / 3600:.1f}h) exceeds the {settings.MAX_VIDEO_DURATION_HOURS}h limit.", 422)

                req_fmts = info.get("requested_formats") or []
                if req_fmts:
                    dl_state["total_streams"] = len(req_fmts)
                    size_est = sum(int(f.get("filesize") or f.get("filesize_approx") or 0) for f in req_fmts)
                else:
                    size_est = int(info.get("filesize") or info.get("filesize_approx") or 0)
                if size_est > 0:
                    check_disk_space(size_est)

                if progress_cb:
                    progress_cb(ImportProgress(
                        stage="DOWNLOADING",
                        progress=5,
                        bytes_transferred=0,
                        total_bytes=size_est or None,
                        message=f"Metadata verified ('{title}') — starting stream download",
                    ))
                dl_state["last_activity"] = time.monotonic()

                # Single-pass download reusing `info` (eliminates duplicate extract_info round-trip)
                if info.get("requested_formats") or info.get("url") or info.get("formats"):
                    res_info = ydl.process_ie_result(info, download=True)
                else:
                    res_info = ydl.extract_info(url, download=True)

                if isinstance(res_info, dict):
                    req_dl = res_info.get("requested_downloads") or []
                    if req_dl and isinstance(req_dl[0], dict) and req_dl[0].get("filepath"):
                        expected_final = Path(req_dl[0]["filepath"])
                    elif res_info.get("_filename"):
                        expected_final = Path(res_info["_filename"])
        except ImportFailure as exc:
            if exc.status == 499:
                _cleanup_partial_downloads(dest_dir)
                if not any(dest_dir.iterdir()) if dest_dir.exists() else False:
                    shutil.rmtree(dest_dir, ignore_errors=True)
            elif not keep_partial_on_error:
                shutil.rmtree(dest_dir, ignore_errors=True)
            raise
        except Exception as exc:
            if not keep_partial_on_error:
                shutil.rmtree(dest_dir, ignore_errors=True)
            msg = str(exc).strip().splitlines()[-1] if str(exc).strip() else "unknown error"
            raise ImportFailure(
                f"Video could not be downloaded (it may be private, restricted or unavailable): {msg}",
                422,
            )
    else:
        # Subprocess fallback when yt-dlp is installed only as an external binary
        ffmpeg_hint = ["--ffmpeg-location", ff_dir] if ff_dir else []
        merge_args = ["--merge-output-format", "mp4"] if ff_dir else []
        args = [
            *cmd,
            "--no-playlist",
            "--no-cookies",
            "--no-warnings",
            "--continue",
            "--socket-timeout", str(sock_timeout),
            "--retries", str(retries),
            "--fragment-retries", str(frag_retries),
            "--extractor-retries", "3",
            "--file-access-retries", "5",
            "--concurrent-fragments", str(frag_N),
            "--http-chunk-size", f"{http_chunk_mb}M",
            "--buffer-size", "65536",
            "--newline",
            "--progress-template",
            "download:VC_PROG|%(progress.downloaded_bytes)s|%(progress.total_bytes)s|%(progress.total_bytes_estimate)s|%(progress.speed)s|%(progress.eta)s",
            "-f", fmt_sel,
            *merge_args,
            "--print", "before_dl:VC_INIT:%(title)s|%(filesize,filesize_approx)s",
            "--print", "after_move:VC_FILEPATH:%(filepath)s",
            "-o", out_tpl,
            *ffmpeg_hint,
            url,
        ]
        popen_kwargs: Dict[str, Any] = {
            "stdout": subprocess.PIPE,
            "stderr": subprocess.STDOUT,
            "text": True,
            "encoding": "utf-8",
            "errors": "replace",
        }
        if os.name == "nt":
            popen_kwargs["creationflags"] = subprocess.CREATE_NEW_PROCESS_GROUP
        else:
            popen_kwargs["start_new_session"] = True

        proc = subprocess.Popen(args, **popen_kwargs)
        if job_id:
            with _procs_guard:
                _active_download_procs[job_id] = proc

        line_q: "queue.Queue[Optional[str]]" = queue.Queue()

        def _reader() -> None:
            try:
                assert proc.stdout is not None
                for ln in proc.stdout:
                    line_q.put(ln)
            finally:
                line_q.put(None)

        threading.Thread(target=_reader, daemon=True).start()

        last_lines: List[str] = []
        start_ts = time.monotonic()
        last_activity = start_ts
        high_pct = 5
        try:
            while True:
                if should_cancel and should_cancel():
                    _kill_process_tree(proc)
                    _cleanup_partial_downloads(dest_dir)
                    raise ImportFailure("Download cancelled by user.", 499)

                now = time.monotonic()
                if now - start_ts > max_dl_sec:
                    _kill_process_tree(proc)
                    raise ImportFailure("Download timed out.", 504)
                if now - last_activity > stall_timeout:
                    _kill_process_tree(proc)
                    raise ImportFailure("Download stalled (no progress before timeout).", 504)

                try:
                    raw_line = line_q.get(timeout=0.4)
                except queue.Empty:
                    if proc.poll() is not None and line_q.empty():
                        break
                    continue

                if raw_line is None:
                    break
                last_activity = time.monotonic()

                line = raw_line.strip()
                if not line:
                    continue
                if line.startswith("VC_INIT:"):
                    parts = line[len("VC_INIT:"):].split("|")
                    title = parts[0].strip() or title
                    est_b = _parse_opt_float(parts[1]) if len(parts) > 1 else None
                    if progress_cb:
                        progress_cb(ImportProgress(
                            stage="DOWNLOADING",
                            progress=5,
                            bytes_transferred=0,
                            total_bytes=int(est_b) if est_b else None,
                            message=f"Metadata verified ('{title}') — starting stream download",
                        ))
                    continue
                if line.startswith("VC_FILEPATH:"):
                    fp = line[len("VC_FILEPATH:"):].strip()
                    if fp:
                        expected_final = Path(fp)
                    continue

                m = _PROGRESS_RE.search(line)
                if m and progress_cb:
                    dl_b = int(_parse_opt_float(m.group(1)) or 0)
                    tot_b = _parse_opt_float(m.group(2)) or _parse_opt_float(m.group(3))
                    tot_int = int(tot_b) if tot_b else None
                    spd = _parse_opt_float(m.group(4)) or 0.0
                    eta = _parse_opt_float(m.group(5))
                    raw_pct = min(90, max(5, 5 + int((dl_b / tot_int) * 85))) if tot_int and tot_int > 0 else 25
                    high_pct = max(high_pct, raw_pct)
                    progress_cb(
                        ImportProgress(
                            stage="DOWNLOADING",
                            progress=high_pct,
                            bytes_transferred=dl_b,
                            total_bytes=tot_int,
                            speed_bps=round(spd, 1),
                            eta_seconds=round(eta, 1) if eta is not None else None,
                            message=f"Downloading '{title}' from {platform.title()}",
                        )
                    )
                else:
                    last_lines.append(line)
                    if len(last_lines) > 15:
                        last_lines.pop(0)
            proc.wait(timeout=30)
        except ImportFailure:
            raise
        except Exception as exc:
            _kill_process_tree(proc)
            if not keep_partial_on_error:
                shutil.rmtree(dest_dir, ignore_errors=True)
            raise ImportFailure(f"Download interrupted: {exc}", 502)
        finally:
            if job_id:
                with _procs_guard:
                    _active_download_procs.pop(job_id, None)

        if proc.returncode != 0:
            if not keep_partial_on_error:
                shutil.rmtree(dest_dir, ignore_errors=True)
            reason = last_lines[-1] if last_lines else "unknown error"
            raise ImportFailure(
                f"Video could not be downloaded (it may be private, restricted or unavailable): {reason}",
                422,
            )

    if progress_cb:
        progress_cb(ImportProgress(stage="VALIDATING", progress=92, message="Validating downloaded video file"))

    chosen_file = _select_downloaded_file(dest_dir, expected_final)
    if not chosen_file:
        if not keep_partial_on_error:
            shutil.rmtree(dest_dir, ignore_errors=True)
        raise ImportFailure("Download finished but no valid video file was produced.", 502)

    if progress_cb:
        progress_cb(ImportProgress(stage="EXTRACTING_METADATA", progress=96, message="Extracting metadata with FFprobe"))

    try:
        meta = probe_video(chosen_file)
    except BaseException:
        if not keep_partial_on_error:
            shutil.rmtree(dest_dir, ignore_errors=True)
        raise

    return chosen_file, meta, platform, safe_display_name(title)
