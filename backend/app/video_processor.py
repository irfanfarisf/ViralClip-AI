"""FFmpeg integration: trimming, aspect-ratio conversion to 9:16, subject tracking, encoding, progress parsing.

`build_filter_graph`, `build_trajectory_expr`, and `build_render_command` are pure functions (unit-testable without FFmpeg).
`analyze_video_composition` uses OpenCV to detect faces and salient subjects across a clip window for smart reframing.
`run_ffmpeg` executes a command, parses `-progress` output and supports cancellation.
"""
from __future__ import annotations

import os
import subprocess
import threading
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Sequence, Tuple

from backend.app.gpu_config import EncoderInfo, find_ffmpeg

OUT_W, OUT_H = 1080, 1920
FACECAM_H = 480                 # top band (25% of 1920)
GAMEPLAY_H = OUT_H - FACECAM_H  # 1440 -> 1080x1440 = exact 3:4 gameplay region
OUTPUT_FPS = 30

LAYOUTS = (
    "facecam_gameplay",  # Default: Facecam TOP (1080x480) + Gameplay BOTTOM (1080x1440, 3:4)
    "smart_crop",        # 1. Smart vertical crop (dynamic subject/face tracking + manual adjustment)
    "fullscreen",        # 2. Full-screen video (entire horizontal frame preserved on blurred 9:16 canvas)
    "blurred_fit",       # Alias for fullscreen blurred canvas fit
    "gameplay_pip",      # 3. Facecam picture-in-picture overlay on 9:16 video
    "pip",               # Alias for gameplay_pip
    "custom",            # 4. Custom crop (manual {x,y,w,h}, zoom/pan, or custom split)
    "custom_crop",       # Alias for custom
    "center_crop",       # Static 9:16 center/manual crop
    "gameplay_only",     # Alias for 9:16 single-region gameplay crop
    "split_50_50",       # Equal 50/50 split (1080x960 top + 1080x960 bottom)
)

Rect = Tuple[float, float, float, float]        # normalised x, y, w, h within the source frame
Keyframe = Tuple[float, float, float]           # (t_seconds_from_clip_start, cx_norm, cy_norm)


class FFmpegError(RuntimeError):
    pass


class Cancelled(Exception):
    pass


def _norm_offset(val: Any) -> float:
    """Normalise an offset value: values in [-1, 1] are kept as-is; percentages in (-100..100) are scaled."""
    try:
        v = float(val or 0.0)
    except (TypeError, ValueError):
        return 0.0
    return min(max(v, -1.0), 1.0)


def normalize_crop(crop: Optional[Dict]) -> Rect:
    """Turn a user crop spec into a clamped normalised rectangle.

    Accepts either an explicit rect {x,y,w,h} (fractions of the frame) or
    {zoom, offsetX, offsetY} (zoom>=1 shrinks the window; offsets in -1..1 move it
    within the free space). Anything missing defaults to the full frame.
    """
    crop = crop or {}
    if all(k in crop for k in ("x", "y", "w", "h")):
        w = min(max(float(crop["w"]), 0.05), 1.0)
        h = min(max(float(crop["h"]), 0.05), 1.0)
        x = min(max(float(crop["x"]), 0.0), 1.0 - w)
        y = min(max(float(crop["y"]), 0.0), 1.0 - h)
        return x, y, w, h
    zoom = max(float(crop.get("zoom", 1.0) or 1.0), 1.0)
    w = h = 1.0 / zoom
    ox = _norm_offset(crop.get("offsetX", 0.0))
    oy = _norm_offset(crop.get("offsetY", 0.0))
    free = 1.0 - w
    x = min(max(free / 2 + ox * free / 2, 0.0), free)
    y = min(max(free / 2 + oy * free / 2, 0.0), free)
    return x, y, w, h


def _extract_pan(crop: Optional[Dict]) -> Tuple[float, float]:
    """Return normalised pan offsets (ox, oy) in [-1, 1] for aspect-ratio cover cropping."""
    if not crop:
        return 0.0, 0.0
    raw_x = float(crop.get("panX", crop.get("offsetX", 0.0)) or 0.0)
    raw_y = float(crop.get("panY", crop.get("offsetY", 0.0)) or 0.0)
    # Support percentage sliders (e.g. -40..40 from UI) as well as [-1..1]
    if abs(raw_x) > 1.0:
        raw_x = raw_x / 40.0
    if abs(raw_y) > 1.0:
        raw_y = raw_y / 40.0
    return min(max(raw_x, -1.0), 1.0), min(max(raw_y, -1.0), 1.0)


def _cover(rect: Rect, tw: int, th: int, pan: Tuple[float, float] = (0.0, 0.0)) -> str:
    """Crop `rect` from source, scale to cover `(tw, th)` preserving aspect ratio, then crop `(tw, th)`."""
    x, y, w, h = rect
    ox, oy = pan
    base = (
        f"crop=trunc(iw*{w:.5f}/2)*2:trunc(ih*{h:.5f}/2)*2:trunc(iw*{x:.5f}/2)*2:trunc(ih*{y:.5f}/2)*2,"
        f"scale={tw}:{th}:force_original_aspect_ratio=increase:flags=lanczos,"
    )
    if abs(ox) < 1e-4 and abs(oy) < 1e-4:
        return base + f"crop={tw}:{th}"
    px = min(max(0.5 + ox * 0.5, 0.0), 1.0)
    py = min(max(0.5 + oy * 0.5, 0.0), 1.0)
    return base + f"crop={tw}:{th}:trunc((iw-ow)*{px:.4f}/2)*2:trunc((ih-oh)*{py:.4f}/2)*2"


def build_trajectory_expr(points: Sequence[Tuple[float, float]]) -> str:
    """Build a single-quoted FFmpeg eval expression `u(t)` in [0, 1] from `(t, u)` keyframes.

    Uses FFmpeg's native `lt(t,x)`, `gte(t,x)`, and `clip(x,0,1)` functions inside single quotes
    so `avfilter_graph_parse2` treats commas as function argument separators rather than filter separators.
    """
    if not points:
        return "0.5000"
    pts = sorted([(max(0.0, float(t)), min(max(float(u), 0.0), 1.0)) for t, u in points], key=lambda p: p[0])
    vals = [p[1] for p in pts]
    if len(pts) == 1 or (max(vals) - min(vals) < 0.01):
        avg = sum(vals) / len(vals)
        return f"{avg:.4f}"

    terms: List[str] = [f"(lt(t,{pts[0][0]:.3f})*{pts[0][1]:.4f})"]
    for (t0, u0), (t1, u1) in zip(pts[:-1], pts[1:]):
        dt = t1 - t0
        if dt <= 1e-3:
            continue
        slope = (u1 - u0) / dt
        terms.append(f"(gte(t,{t0:.3f})*lt(t,{t1:.3f})*({u0:.4f}{slope:+.4f}*(t-{t0:.3f})))")
    terms.append(f"(gte(t,{pts[-1][0]:.3f})*{pts[-1][1]:.4f})")
    return "clip(" + "+".join(terms) + ",0,1)"


def _smart_cover(
    rect: Rect,
    tw: int,
    th: int,
    pan: Tuple[float, float] = (0.0, 0.0),
    keyframes: Optional[Sequence[Keyframe]] = None,
) -> str:
    """Dynamic reframing filter for `smart_crop`: tracks subject keyframes `(t, cx, cy)` + manual pan/zoom."""
    if not keyframes or len(keyframes) < 2:
        return _cover(rect, tw, th, pan)
    x, y, w, h = rect
    ox, oy = pan
    u_pts: List[Tuple[float, float]] = []
    v_pts: List[Tuple[float, float]] = []
    for t_sec, cx, cy in keyframes:
        # Map subject center cx in [0, 1] to crop window offset u in [0, 1]
        u = min(max((cx - 0.16) / 0.68 + ox * 0.5, 0.0), 1.0)
        v = min(max((cy - 0.16) / 0.68 + oy * 0.5, 0.0), 1.0)
        u_pts.append((t_sec, u))
        v_pts.append((t_sec, v))
    u_expr = build_trajectory_expr(u_pts)
    v_expr = build_trajectory_expr(v_pts)
    return (
        f"crop=trunc(iw*{w:.5f}/2)*2:trunc(ih*{h:.5f}/2)*2:trunc(iw*{x:.5f}/2)*2:trunc(ih*{y:.5f}/2)*2,"
        f"scale={tw}:{th}:force_original_aspect_ratio=increase:flags=lanczos,"
        f"crop={tw}:{th}:'(iw-ow)*{u_expr}':'(ih-oh)*{v_expr}'"
    )


def build_filter_graph(
    layout: str,
    facecam_crop: Optional[Dict] = None,
    gameplay_crop: Optional[Dict] = None,
    ass_filename: Optional[str] = None,
    keyframes: Optional[Sequence[Keyframe]] = None,
    fps: int = OUTPUT_FPS,
) -> str:
    """Return a -filter_complex graph with output label [vout] (1080x1920, 9:16, SAR 1:1, yuv420p)."""
    if layout not in LAYOUTS:
        raise ValueError(f"Unknown layout '{layout}'. Choose from {', '.join(LAYOUTS)}")

    fc_dict = facecam_crop or {}
    gp_dict = gameplay_crop or {}
    fc = normalize_crop(fc_dict)
    gp = normalize_crop(gp_dict)
    fc_pan = _extract_pan(fc_dict)
    gp_pan = _extract_pan(gp_dict)

    if layout == "facecam_gameplay":
        # Default: Facecam TOP (480px) + Gameplay BOTTOM (1440px -> 1080x1440 = 3:4).
        # Respects optional custom heightPercent when explicitly overridden.
        hp = float(fc_dict.get("heightPercent") or 25.0)
        fc_h = int(round(OUT_H * min(max(hp, 15.0), 55.0) / 100.0 / 2.0) * 2) if "heightPercent" in fc_dict else FACECAM_H
        gp_h = OUT_H - fc_h
        body = (
            f"[0:v]split=2[fa][ga];"
            f"[fa]{_cover(fc, OUT_W, fc_h, fc_pan)}[face];"
            f"[ga]{_cover(gp, OUT_W, gp_h, gp_pan)}[game];"
            f"[face][game]vstack=inputs=2"
        )
    elif layout == "split_50_50":
        half_h = OUT_H // 2  # 960px each
        body = (
            f"[0:v]split=2[fa][ga];"
            f"[fa]{_cover(fc, OUT_W, half_h, fc_pan)}[face];"
            f"[ga]{_cover(gp, OUT_W, half_h, gp_pan)}[game];"
            f"[face][game]vstack=inputs=2"
        )
    elif layout == "smart_crop":
        body = f"[0:v]{_smart_cover(gp, OUT_W, OUT_H, gp_pan, keyframes)}"
    elif layout in ("gameplay_pip", "pip"):
        pip_scale = float(fc_dict.get("pipScale") or gp_dict.get("pipScale") or 28.0)
        pip_corner = str(fc_dict.get("pipCorner") or gp_dict.get("pipCorner") or "bottom_right")
        pip_w = int(round(OUT_W * min(max(pip_scale, 15.0), 45.0) / 100.0 / 2.0) * 2)
        pip_h = pip_w
        corners = {
            "top_left": ("36", "72"),
            "top_right": ("W-w-36", "72"),
            "bottom_left": ("36", "H-h-300"),
            "bottom_right": ("W-w-36", "H-h-300"),
        }
        ox_str, oy_str = corners.get(pip_corner, corners["bottom_right"])
        body = (
            f"[0:v]split=2[bg_in][pip_in];"
            f"[bg_in]{_cover(gp, OUT_W, OUT_H, gp_pan)}[bg];"
            f"[pip_in]{_cover(fc, pip_w, pip_h, fc_pan)},"
            f"pad={pip_w + 8}:{pip_h + 8}:4:4:color=0x8B5CF6[pip];"
            f"[bg][pip]overlay={ox_str}:{oy_str}"
        )
    elif layout in ("fullscreen", "blurred_fit"):
        # Full-screen video: whole horizontal source frame preserved over a blurred 9:16 backdrop
        _, oy = gp_pan
        py = min(max(0.5 + oy * 0.35, 0.1), 0.9)
        OverlayY = "(H-h)/2" if abs(oy) < 1e-4 else f"(H-h)*{py:.4f}"
        fg_crop = (
            f"crop=trunc(iw*{gp[2]:.5f}/2)*2:trunc(ih*{gp[3]:.5f}/2)*2:"
            f"trunc(iw*{gp[0]:.5f}/2)*2:trunc(ih*{gp[1]:.5f}/2)*2,"
            if gp != (0.0, 0.0, 1.0, 1.0) else ""
        )
        body = (
            f"[0:v]split=2[bg][fg];"
            f"[bg]scale={OUT_W}:{OUT_H}:force_original_aspect_ratio=increase,crop={OUT_W}:{OUT_H},"
            f"boxblur=25:5[bgb];"
            f"[fg]{fg_crop}scale={OUT_W}:-2:flags=lanczos[fgs];"
            f"[bgb][fgs]overlay=(W-w)/2:{OverlayY}"
        )
    elif layout in ("custom", "custom_crop"):
        # Supports custom dual-region split if `split` is enabled in facecam_crop, or custom single-region crop
        if fc_dict.get("split"):
            hp = float(fc_dict.get("heightPercent") or 35.0)
            fc_h = int(round(OUT_H * min(max(hp, 15.0), 75.0) / 100.0 / 2.0) * 2)
            gp_h = OUT_H - fc_h
            body = (
                f"[0:v]split=2[fa][ga];"
                f"[fa]{_cover(fc, OUT_W, fc_h, fc_pan)}[face];"
                f"[ga]{_cover(gp, OUT_W, gp_h, gp_pan)}[game];"
                f"[face][game]vstack=inputs=2"
            )
        else:
            custom_rect = normalize_crop(gp_dict if gp_dict else fc_dict)
            custom_pan = gp_pan if gp_dict else fc_pan
            body = f"[0:v]{_cover(custom_rect, OUT_W, OUT_H, custom_pan)}"
    else:  # gameplay_only, center_crop
        body = f"[0:v]{_cover(gp, OUT_W, OUT_H, gp_pan)}"

    target_fps = min(max(int(fps or OUTPUT_FPS), 15), 60)
    tail = f",fps={target_fps},setsar=1"
    if ass_filename:
        tail += f",ass={ass_filename}"
    tail += ",format=yuv420p"
    return body + tail + "[vout]"


def analyze_video_composition(
    src_path: str,
    start: float,
    end: float,
    num_samples: int = 8,
) -> Dict[str, Any]:
    """Inspect clip frames with OpenCV to detect faces, corner webcams, and salient subject trajectories.

    Never fabricates a second video stream: reports `source_streams=1` and whether an embedded face/webcam
    was actually found in the frames.
    """
    duration = max(0.1, end - start)
    fallback: Dict[str, Any] = {
        "source_streams": 1,
        "single_source_reframed": True,
        "face_detected": False,
        "corner_webcam_detected": False,
        "primary_subject": "center",
        "auto_facecam_crop": None,
        "auto_gameplay_crop": {"x": 0.0, "y": 0.0, "w": 1.0, "h": 1.0},
        "subject_keyframes": [(0.0, 0.5, 0.5), (round(duration, 2), 0.5, 0.5)],
    }
    if not src_path or not os.path.exists(src_path):
        return fallback

    try:
        import cv2
        import numpy as np
    except ImportError:
        return fallback

    cap = cv2.VideoCapture(src_path)
    if not cap.isOpened():
        return fallback

    try:
        cascade_path = os.path.join(cv2.data.haarcascades, "haarcascade_frontalface_default.xml")
        face_cascade = cv2.CascadeClassifier(cascade_path) if os.path.exists(cascade_path) else None

        n_pts = min(max(num_samples, 3), 12)
        sample_times = [start + duration * i / max(n_pts - 1, 1) for i in range(n_pts)]

        face_boxes: List[Tuple[float, float, float, float]] = []
        raw_centers: List[Tuple[float, float, float]] = []
        prev_gray = None

        for t_abs in sample_times:
            t_rel = round(max(0.0, t_abs - start), 3)
            cap.set(cv2.CAP_PROP_POS_MSEC, t_abs * 1000.0)
            ok, frame = cap.read()
            if not ok or frame is None or frame.size == 0:
                continue

            fh, fw = frame.shape[:2]
            scale_w = 480
            scale_h = max(int(round(fh * (scale_w / max(fw, 1)))), 64)
            small = cv2.resize(frame, (scale_w, scale_h), interpolation=cv2.INTER_AREA)
            gray = cv2.cvtColor(small, cv2.COLOR_BGR2GRAY)

            detected_face: Optional[Tuple[float, float, float, float]] = None
            if face_cascade is not None:
                faces = face_cascade.detectMultiScale(
                    gray, scaleFactor=1.15, minNeighbors=4, minSize=(22, 22)
                )
                if len(faces) > 0:
                    # Pick the largest detected face
                    bx, by, bw, bh = max(faces, key=lambda b: int(b[2]) * int(b[3]))
                    detected_face = (
                        float(bx) / scale_w,
                        float(by) / scale_h,
                        float(bw) / scale_w,
                        float(bh) / scale_h,
                    )
                    face_boxes.append(detected_face)

            # Compute saliency (edges + contrast from background) + motion centroid
            lap = np.abs(cv2.Laplacian(gray, cv2.CV_32F))
            contrast = np.abs(gray.astype(np.float32) - float(np.median(gray)))
            if prev_gray is not None and prev_gray.shape == gray.shape:
                mot = cv2.absdiff(gray, prev_gray).astype(np.float32)
                sal = lap + 0.5 * contrast + 3.0 * mot
            else:
                sal = lap + 0.5 * contrast
            prev_gray = gray

            # Ignore 5% border artifacts
            my, mx = max(int(scale_h * 0.05), 1), max(int(scale_w * 0.05), 1)
            roi = sal[my : scale_h - my, mx : scale_w - mx]
            if roi.size > 0 and float(roi.max()) > 1.0:
                thresh = max(float(np.percentile(roi, 85)), float(roi.max()) * 0.25)
                mask = np.where(roi >= thresh, roi, 0.0)
                total = float(mask.sum())
                if total > 1e-3:
                    ys, xs = np.indices(roi.shape)
                    cx = (float((xs * mask).sum()) / total + mx) / scale_w
                    cy = (float((ys * mask).sum()) / total + my) / scale_h
                else:
                    cx, cy = 0.5, 0.5
            else:
                cx, cy = 0.5, 0.5

            if detected_face is not None:
                fx, fy, fw_n, fh_n = detected_face
                # If it's a main/central face (not a tiny corner overlay), track the face directly
                if fw_n >= 0.14 or (0.25 <= fx + fw_n / 2 <= 0.75):
                    cx = fx + fw_n / 2.0
                    cy = fy + fh_n / 2.0

            raw_centers.append((t_rel, min(max(cx, 0.1), 0.9), min(max(cy, 0.1), 0.9)))

        if not raw_centers:
            return fallback

        # Exponential smoothing of trajectory so panning is smooth and steady
        smoothed: List[Keyframe] = []
        alpha = 0.45
        sx, sy = raw_centers[0][1], raw_centers[0][2]
        for t_rel, cx, cy in raw_centers:
            sx = alpha * cx + (1.0 - alpha) * sx
            sy = alpha * cy + (1.0 - alpha) * sy
            smoothed.append((round(t_rel, 3), round(sx, 4), round(sy, 4)))
        if len(smoothed) == 1:
            smoothed.append((round(duration, 3), smoothed[0][1], smoothed[0][2]))

        auto_fc: Optional[Dict[str, float]] = None
        is_corner_webcam = False
        if face_boxes:
            med_x = sorted(b[0] for b in face_boxes)[len(face_boxes) // 2]
            med_y = sorted(b[1] for b in face_boxes)[len(face_boxes) // 2]
            med_w = sorted(b[2] for b in face_boxes)[len(face_boxes) // 2]
            med_h = sorted(b[3] for b in face_boxes)[len(face_boxes) // 2]
            fcx = med_x + med_w / 2.0
            fcy = med_y + med_h / 2.0
            is_corner_webcam = bool(med_w < 0.25 and (fcx < 0.35 or fcx > 0.65))
            crop_w = min(max(med_w * 2.8, 0.24), 0.75)
            crop_h = min(max(med_h * 2.4, 0.24), 0.75)
            crop_x = min(max(fcx - crop_w / 2.0, 0.0), 1.0 - crop_w)
            crop_y = min(max(fcy - crop_h * 0.45, 0.0), 1.0 - crop_h)
            auto_fc = {
                "x": round(crop_x, 4),
                "y": round(crop_y, 4),
                "w": round(crop_w, 4),
                "h": round(crop_h, 4),
            }

        return {
            "source_streams": 1,
            "single_source_reframed": True,
            "face_detected": bool(face_boxes),
            "corner_webcam_detected": is_corner_webcam,
            "primary_subject": "face" if face_boxes else "motion_saliency",
            "auto_facecam_crop": auto_fc,
            "auto_gameplay_crop": {"x": 0.0, "y": 0.0, "w": 1.0, "h": 1.0},
            "subject_keyframes": smoothed,
        }
    finally:
        cap.release()


def build_render_command(
    ffmpeg: str,
    src: str,
    out: str,
    start: float,
    duration: float,
    filter_graph: str,
    encoder: EncoderInfo,
    has_audio: bool,
    fps: int = OUTPUT_FPS,
    audio_bitrate_kbps: int = 160,
    audio_stream_index: int = 0,
) -> List[str]:
    target_fps = min(max(int(fps or OUTPUT_FPS), 15), 60)
    ab_k = min(max(int(audio_bitrate_kbps or 160), 64), 320)
    a_idx = max(0, int(audio_stream_index or 0))
    cmd = [
        ffmpeg, "-hide_banner", "-y", "-loglevel", "error", "-nostdin",
        "-ss", f"{start:.3f}", "-t", f"{duration:.3f}", "-i", src,
        "-filter_complex", filter_graph, "-map", "[vout]",
    ]
    if has_audio:
        cmd += ["-map", f"0:a:{a_idx}", "-af", "aresample=48000:async=1:first_pts=0",
                "-c:a", "aac", "-b:a", f"{ab_k}k", "-ar", "48000", "-ac", "2"]
    else:
        cmd += ["-an"]
    cmd += [
        "-c:v", encoder.name, *encoder.args,
        "-r", str(target_fps), "-fps_mode", "cfr", "-g", str(target_fps * 2),
        "-movflags", "+faststart", "-t", f"{duration:.3f}",
        "-progress", "pipe:1", "-nostats", out,
    ]
    return cmd


def run_ffmpeg(
    cmd: List[str],
    duration: float,
    progress_cb: Optional[Callable[[float], None]] = None,
    should_cancel: Optional[Callable[[], bool]] = None,
    cwd: Optional[str] = None,
    timeout: float = 3 * 3600,
) -> None:
    """Run FFmpeg, report progress 0..1 from `-progress` output, raise FFmpegError on failure."""
    proc = subprocess.Popen(
        cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, cwd=cwd,
    )
    stderr_buf: List[str] = []

    def _drain():
        for line in proc.stderr:  # type: ignore[union-attr]
            stderr_buf.append(line)

    t = threading.Thread(target=_drain, daemon=True)
    t.start()
    timer = threading.Timer(timeout, proc.kill)
    timer.start()
    try:
        for line in proc.stdout:  # type: ignore[union-attr]
            if should_cancel and should_cancel():
                proc.kill()
                proc.wait()
                raise Cancelled()
            if line.startswith("out_time_us=") or line.startswith("out_time_ms="):
                try:
                    secs = int(line.split("=")[1]) / 1_000_000
                except ValueError:
                    continue
                if progress_cb and duration > 0:
                    progress_cb(min(max(secs / duration, 0.0), 1.0))
        rc = proc.wait()
    finally:
        timer.cancel()
        if proc.poll() is None:
            proc.kill()
            proc.wait()
        t.join(timeout=2)
        if proc.stdout:
            proc.stdout.close()
        if proc.stderr:
            proc.stderr.close()
    if rc != 0:
        raise FFmpegError("".join(stderr_buf).strip()[-1500:] or f"ffmpeg exited with code {rc}")


def trim_clip(src: str, out: str, start: float, end: float, encoder: EncoderInfo, has_audio: bool = True) -> None:
    """Frame-accurate trim (re-encode, original aspect ratio) of [start, end] seconds."""
    ffmpeg = find_ffmpeg()
    if not ffmpeg:
        raise FFmpegError("FFmpeg is not installed")
    dur = end - start
    if dur <= 0:
        raise ValueError("end must be greater than start")
    cmd = [ffmpeg, "-hide_banner", "-y", "-loglevel", "error", "-nostdin",
           "-ss", f"{start:.3f}", "-t", f"{dur:.3f}", "-i", src,
           "-c:v", encoder.name, *encoder.args, "-pix_fmt", "yuv420p"]
    cmd += ["-c:a", "aac", "-b:a", "160k"] if has_audio else ["-an"]
    cmd += ["-movflags", "+faststart", out]
    run_ffmpeg(cmd, dur)


def validate_extracted_wav(wav_path: str, expected_duration: float = 0.0) -> bool:
    """Verify that `wav_path` is a valid, non-empty 16 kHz mono 16-bit PCM WAV file matching expected duration."""
    import wave
    p = Path(wav_path)
    if not p.exists() or p.stat().st_size <= 44:
        return False
    try:
        with wave.open(str(p), "rb") as wf:
            if wf.getsampwidth() != 2 or wf.getframerate() != 16000 or wf.getnchannels() != 1:
                return False
            n_frames = wf.getnframes()
            if n_frames <= 0:
                return False
            wav_dur = n_frames / 16000.0
            if expected_duration > 1.0 and abs(wav_dur - expected_duration) > max(2.5, expected_duration * 0.03):
                return False
        return True
    except Exception:
        return False


def extract_audio_wav(
    src: str,
    out_wav: str,
    duration: float = 0.0,
    progress_cb: Optional[Callable[[float], None]] = None,
    should_cancel: Optional[Callable[[], bool]] = None,
    reuse_cached: bool = True,
) -> dict:
    """Extract 16 kHz mono PCM WAV without decoding video frames (-vn -map 0:a:0).
    Reuses valid cached WAV if already extracted; validates extracted audio before returning.
    """
    if reuse_cached and validate_extracted_wav(out_wav, duration):
        if progress_cb:
            progress_cb(1.0)
        return {"path": out_wav, "cached": True}

    ffmpeg = find_ffmpeg()
    if not ffmpeg:
        raise FFmpegError("FFmpeg is not installed")
    out_p = Path(out_wav)
    out_p.parent.mkdir(parents=True, exist_ok=True)
    part_p = out_p.with_suffix(".extracting.part.wav")
    try:
        cmd = [
            ffmpeg, "-hide_banner", "-y", "-loglevel", "error", "-nostdin",
            "-i", src,
            "-vn", "-map", "0:a:0",
            "-ac", "1", "-ar", "16000", "-c:a", "pcm_s16le",
            "-progress", "pipe:1", "-nostats",
            str(part_p),
        ]
        run_ffmpeg(cmd, duration, progress_cb=progress_cb, should_cancel=should_cancel)
        if not validate_extracted_wav(str(part_p), 0.0):
            raise FFmpegError("Extracted audio WAV failed 16 kHz mono PCM validation.")
        os.replace(part_p, out_p)
    except BaseException:
        part_p.unlink(missing_ok=True)
        raise
    return {"path": out_wav, "cached": False}
