"""Locate FFmpeg/FFprobe and detect which H.264 encoders actually work on this machine.

An encoder is only reported as available after a real 1-frame test encode succeeds,
not merely because it is listed in `ffmpeg -encoders`. CPU (libx264) is the fallback.
All subprocess work is synchronous; call from threads (asyncio.to_thread) in async code.
"""
from __future__ import annotations

import os
import shutil
import subprocess
import threading
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Dict, List, Optional

from backend.app.config import settings

PROJECT_ROOT = Path(__file__).resolve().parents[2]


def _find_binary(name: str, configured: str) -> Optional[str]:
    if configured and Path(configured).exists():
        return str(Path(configured))
    found = shutil.which(name)
    if found:
        return found
    # Project-local install: <root>/tools/**/bin/<name>(.exe)
    tools = PROJECT_ROOT / "tools"
    if tools.exists():
        for cand in tools.rglob(f"{name}.exe"):
            return str(cand)
        for cand in tools.rglob(name):
            if cand.is_file():
                return str(cand)
    # Common Windows 11 locations (Winget / C:\ffmpeg\bin)
    local_app = os.environ.get("LOCALAPPDATA")
    if local_app:
        winget_pkgs = Path(local_app) / "Microsoft" / "WinGet" / "Packages"
        if winget_pkgs.exists():
            for cand in winget_pkgs.glob(f"*FFmpeg*/**/{name}.exe"):
                return str(cand)
    win_default = Path(f"C:/ffmpeg/bin/{name}.exe")
    if win_default.exists():
        return str(win_default)
    return None


def find_ffmpeg() -> Optional[str]:
    return _find_binary("ffmpeg", settings.FFMPEG_PATH)


def find_ffprobe() -> Optional[str]:
    return _find_binary("ffprobe", settings.FFPROBE_PATH)


@dataclass
class EncoderInfo:
    name: str                 # ffmpeg codec name, e.g. h264_nvenc
    kind: str                 # "hardware" | "software"
    label: str                # human readable
    args: List[str] = field(default_factory=list)  # quality/rate args

    def to_dict(self) -> dict:
        return asdict(self)


# (codec, label, default quality args). Order = preference: NVIDIA NVENC -> Intel QSV -> AMD AMF -> VideoToolbox.
_HW_CANDIDATES = [
    ("h264_nvenc", "NVIDIA NVENC (h264_nvenc)", ["-preset", "p4", "-rc", "vbr", "-cq", "22", "-b:v", "0"]),
    ("h264_qsv", "Intel Quick Sync (h264_qsv)", ["-global_quality", "23", "-preset", "medium"]),
    ("h264_amf", "AMD AMF (h264_amf)", ["-quality", "balanced", "-rc", "cqp", "-qp_i", "22", "-qp_p", "24"]),
    ("h264_videotoolbox", "Apple VideoToolbox (h264_videotoolbox)", ["-b:v", "8M"]),
]
CPU_ENCODER = EncoderInfo(
    "libx264", "software", "CPU (libx264)", ["-preset", "veryfast", "-crf", "20"]
)

_lock = threading.Lock()
_cache: Dict[str, object] = {}


def configure_encoder(
    encoder: EncoderInfo,
    bitrate_kbps: Optional[int] = None,
    quality: str = "balanced",
) -> EncoderInfo:
    """Return an EncoderInfo copy with rate-control and quality flags for the target bitrate/quality."""
    q = (quality or "balanced").lower()
    if q not in ("high", "balanced", "fast"):
        q = "balanced"
    bk = int(bitrate_kbps) if bitrate_kbps and int(bitrate_kbps) >= 500 else None
    max_bk = int(bk * 1.25) if bk else None
    buf_bk = int(bk * 2) if bk else None

    name = encoder.name
    if name == "h264_nvenc":
        preset = {"high": "p5", "balanced": "p4", "fast": "p2"}[q]
        cq = {"high": "19", "balanced": "22", "fast": "25"}[q]
        args = ["-preset", preset, "-rc", "vbr", "-cq", cq]
        args += ["-b:v", f"{bk}k", "-maxrate", f"{max_bk}k", "-bufsize", f"{buf_bk}k"] if bk else ["-b:v", "0"]
    elif name == "h264_qsv":
        preset = {"high": "slow", "balanced": "medium", "fast": "veryfast"}[q]
        gq = {"high": "20", "balanced": "23", "fast": "26"}[q]
        args = ["-preset", preset]
        args += ["-b:v", f"{bk}k", "-maxrate", f"{max_bk}k"] if bk else ["-global_quality", gq]
    elif name == "h264_amf":
        amf_q = {"high": "quality", "balanced": "balanced", "fast": "speed"}[q]
        qp_i = {"high": "19", "balanced": "22", "fast": "25"}[q]
        qp_p = {"high": "21", "balanced": "24", "fast": "27"}[q]
        if bk:
            args = ["-quality", amf_q, "-rc", "vbr_peak", "-b:v", f"{bk}k", "-maxrate", f"{max_bk}k", "-bufsize", f"{buf_bk}k"]
        else:
            args = ["-quality", amf_q, "-rc", "cqp", "-qp_i", qp_i, "-qp_p", qp_p]
    elif name == "h264_videotoolbox":
        target_b = f"{bk}k" if bk else {"high": "10M", "balanced": "8M", "fast": "5M"}[q]
        args = ["-b:v", target_b]
    else:  # libx264 (CPU)
        preset = {"high": "fast", "balanced": "veryfast", "fast": "ultrafast"}[q]
        crf = {"high": "18", "balanced": "20", "fast": "23"}[q]
        args = ["-preset", preset, "-crf", crf]
        if bk:
            args += ["-maxrate", f"{max_bk}k", "-bufsize", f"{buf_bk}k"]

    return EncoderInfo(name=encoder.name, kind=encoder.kind, label=encoder.label, args=args)


def listed_encoders(ffmpeg: str) -> set[str]:
    """Encoders compiled into this FFmpeg build (`ffmpeg -encoders`)."""
    out = subprocess.run(
        [ffmpeg, "-hide_banner", "-encoders"], capture_output=True, text=True, timeout=20
    ).stdout
    names = set()
    for line in out.splitlines():
        parts = line.split()
        if len(parts) >= 2 and parts[0].startswith("V"):
            names.add(parts[1])
    return names


def probe_encoder(ffmpeg: str, codec: str, args: List[str]) -> bool:
    """Real test encode of a few synthetic frames to the null muxer."""
    cmd = [
        ffmpeg, "-hide_banner", "-loglevel", "error",
        "-f", "lavfi", "-i", "color=c=black:s=256x256:r=30:d=0.2",
        "-c:v", codec, *args, "-pix_fmt", "yuv420p", "-f", "null", "-",
    ]
    try:
        return subprocess.run(cmd, capture_output=True, timeout=25).returncode == 0
    except (subprocess.TimeoutExpired, OSError):
        return False


def detect_encoders(force: bool = False) -> dict:
    """Return {'ffmpeg': path|None, 'ffprobe': ..., 'version': ..., 'working': [...], 'vendors': {...}, 'selected': {...}}."""
    with _lock:
        if _cache and not force:
            return _cache  # type: ignore[return-value]
        ffmpeg, ffprobe = find_ffmpeg(), find_ffprobe()
        result: dict = {
            "ffmpeg": ffmpeg, "ffprobe": ffprobe, "version": None,
            "listed": [], "working": [], "selected": CPU_ENCODER.to_dict(),
            "vendors": {
                "nvenc": {"codec": "h264_nvenc", "label": "NVIDIA NVENC", "listed": False, "available": False},
                "qsv": {"codec": "h264_qsv", "label": "Intel Quick Sync (QSV)", "listed": False, "available": False},
                "amf": {"codec": "h264_amf", "label": "AMD AMF", "listed": False, "available": False},
                "cpu": {"codec": "libx264", "label": "CPU (libx264)", "listed": False, "available": False},
            },
        }
        if ffmpeg:
            try:
                ver = subprocess.run([ffmpeg, "-version"], capture_output=True, text=True, timeout=15).stdout
                result["version"] = ver.splitlines()[0] if ver else None
                listed = listed_encoders(ffmpeg)
                result["listed"] = sorted(c for c, _, _ in _HW_CANDIDATES if c in listed)
                cpu_ok = "libx264" in listed
                result["vendors"]["cpu"]["listed"] = cpu_ok
                result["vendors"]["cpu"]["available"] = cpu_ok
                if not cpu_ok:
                    result["selected"] = None  # cannot encode H.264 at all
                working_names = set()
                for codec, label, args in _HW_CANDIDATES:
                    if codec in listed and probe_encoder(ffmpeg, codec, args):
                        info = EncoderInfo(codec, "hardware", label, args)
                        result["working"].append(info.to_dict())
                        working_names.add(codec)
                for vkey, vinfo in result["vendors"].items():
                    if vkey == "cpu":
                        continue
                    c_name = vinfo["codec"]
                    vinfo["listed"] = c_name in listed
                    vinfo["available"] = c_name in working_names
                if result["working"]:
                    result["selected"] = result["working"][0]
            except (subprocess.TimeoutExpired, OSError) as exc:
                result["error"] = str(exc)
        _cache.clear()
        _cache.update(result)
        return result


def select_encoder(prefer_hardware: bool = True, preferred_codec: Optional[str] = None) -> EncoderInfo:
    info = detect_encoders()
    if not info["ffmpeg"] or info["selected"] is None:
        raise RuntimeError("FFmpeg with libx264 support is not available")
    if preferred_codec:
        if preferred_codec == "libx264":
            return CPU_ENCODER
        for w in info["working"]:
            if w["name"] == preferred_codec:
                return EncoderInfo(**w)
    if prefer_hardware and info["working"]:
        return EncoderInfo(**info["working"][0])
    return CPU_ENCODER
