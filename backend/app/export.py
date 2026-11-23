"""Render a vertical 1080x1920 MP4 for a clip, then validate the file that was actually written.

Validation reads the output with ffprobe: stream layout, codec (H.264/AAC), resolution, frame rate,
duration and container-level audio/video timestamp alignment. This verifies timestamps, not perceived
lip-sync, and it makes no guaranteed 0 ms claim: the pass tolerance is 50 ms start offset / 100 ms duration drift.
GPU acceleration is reported as True only when a hardware encoder actually succeeded on the render.
"""
from __future__ import annotations

import json
import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import Callable, Dict, List, Optional

from backend.app import video_processor as vp
from backend.app.gpu_config import (
    CPU_ENCODER,
    EncoderInfo,
    configure_encoder,
    find_ffmpeg,
    find_ffprobe,
    select_encoder,
)
from backend.app.subtitle_generator import SubtitleStyle, collect_translated_words, collect_words, generate_ass

START_TOLERANCE_MS = 50.0
DURATION_TOLERANCE_MS = 100.0


class ExportError(RuntimeError):
    pass


def probe_output(path: Path) -> dict:
    ffprobe = find_ffprobe()
    if not ffprobe:
        raise ExportError("FFprobe not available for output validation")
    proc = subprocess.run(
        [ffprobe, "-v", "error", "-print_format", "json", "-show_format", "-show_streams", str(path)],
        capture_output=True, text=True, timeout=60,
    )
    if proc.returncode != 0:
        raise ExportError("Rendered file is not readable by ffprobe")
    return json.loads(proc.stdout)


def _f(v) -> Optional[float]:
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def validate_output(
    path: Path,
    expected_duration: float,
    expect_audio: bool,
    expected_fps: Optional[int] = None,
) -> dict:
    """Return a validation report; `passed` is True only when every check holds."""
    checks: Dict[str, bool] = {}
    if not path.exists() or path.stat().st_size == 0:
        return {"passed": False, "checks": {"file_exists": False}, "errors": ["Output file missing or empty"]}
    data = probe_output(path)
    streams = data.get("streams", [])
    fmt = data.get("format", {})
    v = next((s for s in streams if s["codec_type"] == "video"), None)
    a = next((s for s in streams if s["codec_type"] == "audio"), None)
    errors: List[str] = []

    checks["video_stream"] = v is not None
    checks["resolution_1080x1920"] = bool(v and v.get("width") == vp.OUT_W and v.get("height") == vp.OUT_H)
    checks["codec_h264"] = bool(v and v.get("codec_name") == "h264")
    checks["audio_stream"] = (a is not None) if expect_audio else True
    if expect_audio and a is not None:
        checks["codec_aac"] = a.get("codec_name") == "aac"

    vdur = _f(v.get("duration")) if v else None
    adur = _f(a.get("duration")) if a else None
    fdur = _f(fmt.get("duration"))
    vdur = vdur or fdur
    checks["duration_matches"] = bool(vdur and abs(vdur - expected_duration) <= 0.5)

    start_offset_ms = duration_delta_ms = None
    if v and a:
        vs, as_ = _f(v.get("start_time")) or 0.0, _f(a.get("start_time")) or 0.0
        start_offset_ms = round((as_ - vs) * 1000, 1)
        checks["av_start_offset_ok"] = abs(start_offset_ms) <= START_TOLERANCE_MS
        if vdur and adur:
            duration_delta_ms = round((adur - vdur) * 1000, 1)
            checks["av_duration_drift_ok"] = abs(duration_delta_ms) <= DURATION_TOLERANCE_MS

    def _rate(s):
        try:
            n, d = s.split("/")
            return float(n) / float(d)
        except (ValueError, ZeroDivisionError, AttributeError):
            return 0.0

    fps_val = None
    if v:
        r, avg = _rate(v.get("r_frame_rate", "")), _rate(v.get("avg_frame_rate", ""))
        fps_val = round(avg, 3) if avg else None
        checks["constant_frame_rate"] = bool(r and avg and abs(r - avg) / r < 0.01)
        if expected_fps:
            checks["fps_matches"] = bool(avg and abs(avg - expected_fps) <= 1.0)

    raw_br = _f(fmt.get("bit_rate")) or (_f(v.get("bit_rate")) if v else None)
    bitrate_kbps = round(raw_br / 1000.0, 1) if raw_br else None

    errors = [k for k, ok in checks.items() if not ok]
    return {
        "passed": not errors,
        "checks": checks,
        "failed_checks": errors,
        "sync_offset_ms": start_offset_ms,           # audio start - video start (container timestamps)
        "audio_video_duration_delta_ms": duration_delta_ms,
        "tolerance_ms": {"start_offset": START_TOLERANCE_MS, "duration_drift": DURATION_TOLERANCE_MS},
        "video_duration": vdur,
        "audio_duration": adur,
        "width": v.get("width") if v else None,
        "height": v.get("height") if v else None,
        "codec": v.get("codec_name") if v else None,
        "audio_codec": a.get("codec_name") if a else None,
        "fps": fps_val,
        "bitrate_kbps": bitrate_kbps,
        "method": "ffprobe container timestamps (not a perceptual lip-sync test; tolerance ±50ms start / ±100ms drift)",
    }


def render_clip(
    src_path: str,
    out_path: Path,
    start: float,
    end: float,
    has_audio: bool,
    layout: str = "facecam_gameplay",
    facecam_crop: Optional[Dict] = None,
    gameplay_crop: Optional[Dict] = None,
    segments: Optional[List[dict]] = None,
    subtitle_style: Optional[Dict] = None,
    burn_subtitles: bool = True,
    progress_cb: Optional[Callable[[float], None]] = None,
    should_cancel: Optional[Callable[[], bool]] = None,
    prefer_hardware: bool = True,
    fps: int = vp.OUTPUT_FPS,
    bitrate_kbps: Optional[int] = None,
    quality: str = "balanced",
    audio_bitrate_kbps: int = 160,
    preferred_encoder: Optional[str] = None,
) -> dict:
    """Render and validate. Falls back to CPU if the hardware encoder fails at runtime."""
    ffmpeg = find_ffmpeg()
    if not ffmpeg:
        raise ExportError("FFmpeg is not installed on the server")
    if end <= start:
        raise ExportError("Clip end must be after start")
    duration = end - start
    target_fps = min(max(int(fps or vp.OUTPUT_FPS), 15), 60)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    part = out_path.with_suffix(".part.mp4")
    work = Path(tempfile.mkdtemp(prefix="render_", dir=str(out_path.parent)))
    try:
        ass_name = None
        words: List[dict] = []
        st_dict = dict(subtitle_style or {})
        style_enabled_raw = st_dict.get("enabled", True)
        style_enabled = (
            style_enabled_raw
            if isinstance(style_enabled_raw, bool)
            else str(style_enabled_raw).strip().lower() not in ("false", "0", "no", "off")
        )
        if burn_subtitles and style_enabled:
            trans_words = st_dict.get("translated_words") or st_dict.get("translatedWords")
            if trans_words:
                words = collect_translated_words(trans_words, start, end)
            if not words and segments:
                words = collect_words(segments, start, end)
            if words:
                (work / "subs.ass").write_text(
                    generate_ass(words, SubtitleStyle.from_dict(st_dict)), encoding="utf-8-sig")
                ass_name = "subs.ass"

        comp = vp.analyze_video_composition(src_path, start, end)
        effective_fc = dict(facecam_crop or {})
        has_manual_fc = any(k in effective_fc for k in ("x", "y", "w", "h", "zoom", "offsetX", "offsetY"))
        if not has_manual_fc and comp.get("auto_facecam_crop") and layout in ("facecam_gameplay", "gameplay_pip", "pip"):
            effective_fc = {**comp["auto_facecam_crop"], **effective_fc}

        graph = vp.build_filter_graph(
            layout, effective_fc, gameplay_crop, ass_name, keyframes=comp.get("subject_keyframes"), fps=target_fps
        )

        try:
            primary_enc = select_encoder(prefer_hardware=prefer_hardware, preferred_codec=preferred_encoder)
        except RuntimeError as exc:
            raise ExportError(str(exc))

        configured_primary = configure_encoder(primary_enc, bitrate_kbps=bitrate_kbps, quality=quality)
        configured_cpu = configure_encoder(CPU_ENCODER, bitrate_kbps=bitrate_kbps, quality=quality)
        attempts = [configured_primary] + ([configured_cpu] if configured_primary.kind == "hardware" else [])

        used: Optional[EncoderInfo] = None
        last_err = ""
        for enc in attempts:
            cmd = vp.build_render_command(
                ffmpeg, str(Path(src_path).resolve()), str(part.resolve()),
                start, duration, graph, enc, has_audio, fps=target_fps, audio_bitrate_kbps=audio_bitrate_kbps
            )
            try:
                vp.run_ffmpeg(cmd, duration, progress_cb, should_cancel, cwd=str(work))
                used = enc
                break
            except vp.FFmpegError as exc:
                last_err = str(exc)
                part.unlink(missing_ok=True)
        if used is None:
            raise ExportError(f"FFmpeg render failed: {last_err}")

        report = validate_output(part, duration, has_audio, expected_fps=target_fps)
        gpu_used = used.kind == "hardware"
        fallback_used = (used.kind == "software" and configured_primary.kind == "hardware")
        report["composition"] = {
            "layout": layout,
            "source_streams": comp["source_streams"],
            "single_source_reframed": comp["single_source_reframed"],
            "face_detected": comp["face_detected"],
            "corner_webcam_detected": comp["corner_webcam_detected"],
            "primary_subject": comp["primary_subject"],
            "dynamic_tracking": layout == "smart_crop",
        }
        report["encoder"] = used.label
        report["encoder_codec"] = used.name
        report["encoder_kind"] = used.kind
        report["gpu_accelerated"] = gpu_used
        report["encoder_fallback_used"] = fallback_used
        report["resolution"] = f"{report['width']}x{report['height']}"
        report["subtitle_words"] = len(words)

        if not report["passed"]:
            raise ExportError("Output validation failed: " + ", ".join(report["failed_checks"]))
        part.replace(out_path)
        size_mb = round(out_path.stat().st_size / 1048576, 2)
        return {
            "path": str(out_path),
            "size_mb": size_mb,
            "file_size_mb": size_mb,
            "duration": report["video_duration"],
            "resolution": f"{report['width']}x{report['height']}",
            "codec": report["codec"],
            "audio_codec": report["audio_codec"],
            "fps": report["fps"],
            "bitrate_kbps": report["bitrate_kbps"],
            "encoder": used.to_dict(),
            "encoder_used": used.label,
            "gpu_accelerated": gpu_used,
            "fallback_used": fallback_used,
            "subtitle_words": len(words),
            "composition": report["composition"],
            "sync_report": report,
        }
    finally:
        part.unlink(missing_ok=True)
        shutil.rmtree(work, ignore_errors=True)
