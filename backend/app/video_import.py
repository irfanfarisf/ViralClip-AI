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
import re
import shutil
import subprocess
import sys
import threading
import time
import uuid
from dataclasses import dataclass, asdict
from fractions import Fraction
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple
from urllib.parse import urlparse

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
    audio = next((s for s in streams if s.get("codec_type") == "audio"), None)

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
    return session


def get_upload_session(upload_id: str) -> dict:
    meta_file = _session_meta_path(upload_id)
    if not meta_file.exists():
        raise ImportFailure("Upload session not found or already finalized.", 404)
    try:
        return json.loads(meta_file.read_text(encoding="utf-8"))
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

        chunk_len = len(data)
        if chunk_len == 0:
            raise ImportFailure("Chunk payload is empty.", 400)

        calc_offset = int(offset) if offset is not None else chunk_index * chunk_sz
        if calc_offset < 0 or calc_offset + chunk_len > total_bytes:
            raise ImportFailure(
                f"Chunk range {calc_offset}..{calc_offset + chunk_len} exceeds total file size ({total_bytes} bytes).",
                422,
            )

        actual_sha256 = hashlib.sha256(data).hexdigest()
        if expected_sha256 and actual_sha256.lower() != expected_sha256.strip().lower():
            raise ImportFailure(
                f"Chunk {chunk_index} SHA-256 checksum mismatch (expected {expected_sha256[:12]}..., got {actual_sha256[:12]}...).",
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
        _session_meta_path(upload_id).write_text(json.dumps(session), encoding="utf-8")

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
            _upload_locks.pop(upload_id, None)
            raise

        # Remove upload session state file now that source.<ext> is finalized and verified
        _session_meta_path(upload_id).unlink(missing_ok=True)
        _upload_locks.pop(upload_id, None)
        return final_path, meta, session


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
        _upload_locks.pop(upload_id, None)
        return {"upload_id": upload_id, "status": "CANCELLED", "job_id": session.get("job_id")}


# ---------------------------------------------------------------- external import (YouTube / Twitch)

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
    import importlib.util
    if importlib.util.find_spec("yt_dlp") is not None:
        return [sys.executable, "-m", "yt_dlp"]
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


def import_external(
    url: str,
    dest_dir: Path,
    *,
    progress_cb: Optional[Callable[[ImportProgress], None]] = None,
    should_cancel: Optional[Callable[[], bool]] = None,
    keep_partial_on_error: bool = False,
    concurrent_fragments: Optional[int] = None,
) -> Tuple[Path, VideoMetadata, str, str]:
    """Download a public YouTube/Twitch video the user is authorized to use via yt-dlp.

    - Resolves metadata & stream formats first (advancing out of 2% INITIALIZING immediately).
    - Streams real progress updates (downloaded_bytes, total_bytes, speed_bps, eta_seconds) via `progress_cb`.
    - Supports configurable fragment concurrency, socket timeouts, resuming partial downloads (`continuedl`), and retries.
    - Supports mid-download cancellation via `should_cancel`.
    - Does NOT transcode video streams (remux/stream-copy only).
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
    fmt_sel = "bv*[ext=mp4][height<=1080]+ba[ext=m4a]/b[ext=mp4][height<=1080]/bv*[height<=1080]+ba/b[height<=1080]/b"

    if progress_cb:
        progress_cb(ImportProgress(
            stage="INITIALIZING",
            progress=2,
            message=f"Connecting to {platform.title()} and extracting video metadata...",
        ))

    title = f"{platform} video"

    # Prefer native Python yt_dlp module for direct progress_hooks and pre-download metadata check
    try:
        import yt_dlp as _ytdlp_mod
        has_py_ytdlp = True
    except ImportError:
        has_py_ytdlp = False

    if has_py_ytdlp:
        def _hook(d: dict) -> None:
            if should_cancel and should_cancel():
                raise ImportFailure("Download cancelled by user.", 499)
            st = d.get("status")
            if st == "downloading" and progress_cb:
                dl_b = int(d.get("downloaded_bytes") or 0)
                tot_raw = d.get("total_bytes") or d.get("total_bytes_estimate")
                tot_int = int(tot_raw) if tot_raw else None
                spd = float(d.get("speed") or 0.0)
                eta_raw = d.get("eta")
                eta_val = round(float(eta_raw), 1) if eta_raw is not None else None
                if tot_int and tot_int > 0:
                    pct = min(90, max(5, 5 + int((dl_b / tot_int) * 85)))
                else:
                    frag_idx = int(d.get("fragment_index") or 0)
                    frag_cnt = int(d.get("fragment_count") or 0)
                    pct = min(90, max(5, 5 + int((frag_idx / frag_cnt) * 85))) if frag_cnt > 0 else 15
                progress_cb(ImportProgress(
                    stage="DOWNLOADING",
                    progress=pct,
                    bytes_transferred=dl_b,
                    total_bytes=tot_int,
                    speed_bps=round(spd, 1),
                    eta_seconds=eta_val,
                    chunks_received=int(d.get("fragment_index") or 0),
                    total_chunks=int(d.get("fragment_count") or 0),
                    message=f"Downloading '{title}' from {platform.title()}",
                ))
            elif st == "finished" and progress_cb:
                dl_b = int(d.get("downloaded_bytes") or d.get("total_bytes") or 0)
                progress_cb(ImportProgress(
                    stage="DOWNLOADING",
                    progress=90,
                    bytes_transferred=dl_b,
                    total_bytes=dl_b or None,
                    speed_bps=0.0,
                    eta_seconds=0.0,
                    message="Stream download complete; muxing container...",
                ))

        ydl_opts: Dict[str, Any] = {
            "format": fmt_sel,
            "merge_output_format": "mp4",
            "outtmpl": out_tpl,
            "noplaylist": True,
            "continuedl": True,
            "nopart": False,
            "retries": 5,
            "fragment_retries": 5,
            "concurrent_fragment_downloads": frag_N,
            "socket_timeout": sock_timeout,
            "quiet": True,
            "no_warnings": True,
            "progress_hooks": [_hook],
        }
        if ff_dir:
            ydl_opts["ffmpeg_location"] = ff_dir

        try:
            with _ytdlp_mod.YoutubeDL(ydl_opts) as ydl:
                if should_cancel and should_cancel():
                    raise ImportFailure("Download cancelled by user.", 499)
                info = ydl.extract_info(url, download=False)
                if not info:
                    raise ImportFailure("Could not resolve video metadata from URL.", 422)
                title = str(info.get("title") or title)
                dur_est = float(info.get("duration") or 0.0)
                max_s = settings.MAX_VIDEO_DURATION_HOURS * 3600
                if dur_est > max_s:
                    raise ImportFailure(f"Video duration ({dur_est / 3600:.1f}h) exceeds the {settings.MAX_VIDEO_DURATION_HOURS}h limit.", 422)
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
                ydl.download([url])
        except ImportFailure:
            if not keep_partial_on_error:
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
        args = [
            *cmd,
            "--no-playlist",
            "--no-cookies",
            "--no-warnings",
            "--continue",
            "--socket-timeout", str(sock_timeout),
            "--retries", "5",
            "--fragment-retries", "5",
            "--concurrent-fragments", str(frag_N),
            "--newline",
            "--progress-template",
            "download:VC_PROG|%(progress.downloaded_bytes)s|%(progress.total_bytes)s|%(progress.total_bytes_estimate)s|%(progress.speed)s|%(progress.eta)s",
            "-f", fmt_sel,
            "--merge-output-format", "mp4",
            "--print", "before_dl:VC_INIT:%(title)s|%(filesize,filesize_approx)s",
            "--print", "after_move:VC_TITLE:%(title)s",
            "-o", out_tpl,
            *ffmpeg_hint,
            url,
        ]
        proc = subprocess.Popen(
            args,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            encoding="utf-8",
            errors="replace",
        )
        last_lines: List[str] = []
        start_ts = time.time()
        try:
            assert proc.stdout is not None
            for raw_line in proc.stdout:
                if should_cancel and should_cancel():
                    proc.terminate()
                    try:
                        proc.wait(timeout=5)
                    except subprocess.TimeoutExpired:
                        proc.kill()
                    if not keep_partial_on_error:
                        for p in dest_dir.glob("*.part*"):
                            p.unlink(missing_ok=True)
                    raise ImportFailure("Download cancelled by user.", 499)

                if time.time() - start_ts > 14400:
                    proc.kill()
                    raise ImportFailure("Download timed out.", 504)

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
                if line.startswith("VC_TITLE:"):
                    title = line[len("VC_TITLE:"):].strip() or title
                    continue

                m = _PROGRESS_RE.search(line)
                if m and progress_cb:
                    dl_b = int(_parse_opt_float(m.group(1)) or 0)
                    tot_b = _parse_opt_float(m.group(2)) or _parse_opt_float(m.group(3))
                    tot_int = int(tot_b) if tot_b else None
                    spd = _parse_opt_float(m.group(4)) or 0.0
                    eta = _parse_opt_float(m.group(5))
                    pct = min(90, max(5, 5 + int((dl_b / tot_int) * 85))) if tot_int and tot_int > 0 else 25
                    progress_cb(
                        ImportProgress(
                            stage="DOWNLOADING",
                            progress=pct,
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
            proc.kill()
            if not keep_partial_on_error:
                shutil.rmtree(dest_dir, ignore_errors=True)
            raise ImportFailure(f"Download interrupted: {exc}", 502)

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

    files = [
        p for p in dest_dir.glob("source.*")
        if p.suffix.lower() in ALLOWED_EXTENSIONS and not p.name.endswith(".part")
    ]
    if not files:
        if not keep_partial_on_error:
            shutil.rmtree(dest_dir, ignore_errors=True)
        raise ImportFailure("Download finished but no valid video file was produced.", 502)

    if progress_cb:
        progress_cb(ImportProgress(stage="EXTRACTING_METADATA", progress=96, message="Extracting metadata with FFprobe"))

    try:
        meta = probe_video(files[0])
    except BaseException:
        if not keep_partial_on_error:
            shutil.rmtree(dest_dir, ignore_errors=True)
        raise

    return files[0], meta, platform, safe_display_name(title)
