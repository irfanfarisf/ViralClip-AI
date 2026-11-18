"""Optimized local speech recognition with faster-whisper (word-level timestamps & windowed streaming).

Supports:
- Automatic language detection (when language is None or 'auto')
- Configurable Whisper models ('tiny', 'base', 'small', 'medium', 'large-v3') with default 'base'
- Hardware auto-detection: probes actual CTranslate2 CUDA GPU support (float16) vs CPU (int8) with tuned threads
  (never assumes NVENC/AMF video encoding implies Whisper GPU inference)
- Windowed long-audio processing (10-minute WAV slices read directly from disk, < 40 MB audio RAM on 3-4h videos)
- Intermediate checkpoint callbacks and resume-from-timestamp recovery
- Real-time telemetry: transcribed duration, total duration, percentage, model, device, speed (x RT), and ETA
"""
from __future__ import annotations

import logging
import os
import threading
import time
import wave
from typing import Any, Callable, Dict, List, Optional, Tuple

import numpy as np

from backend.app.config import settings

log = logging.getLogger("viralclip.transcription")

SUPPORTED_MODELS = ("tiny", "base", "small", "medium", "large-v3")


BOUNDARY_LOOKAHEAD_S = 20.0


class TranscriptionError(RuntimeError):
    pass


_models: Dict[str, Tuple[Any, dict]] = {}
_models_lock = threading.Lock()


def whisper_available() -> bool:
    import importlib.util
    return importlib.util.find_spec("faster_whisper") is not None


def optimal_cpu_threads() -> int:
    configured = int(getattr(settings, "WHISPER_CPU_THREADS", 0) or 0)
    if configured > 0:
        return configured
    logical = os.cpu_count() or 4
    # Leave 1-2 threads free for FastAPI/OS responsiveness on a 16 GB Windows 11 machine
    return max(2, min(8, logical - 1 if logical > 2 else logical))


def detect_whisper_hardware(
    requested_device: Optional[str] = None,
    requested_compute: Optional[str] = None,
) -> dict:
    """Detect whether CTranslate2 CUDA GPU inference is actually supported, or configure optimal CPU int8."""
    req_dev = (requested_device or settings.WHISPER_DEVICE or "auto").strip().lower()
    req_comp = (requested_compute or settings.WHISPER_COMPUTE_TYPE or "auto").strip().lower()

    cuda_count = 0
    supported_cuda_types: set[str] = set()
    try:
        import ctranslate2
        cuda_count = int(ctranslate2.get_cuda_device_count() or 0)
        if cuda_count > 0:
            supported_cuda_types = set(ctranslate2.get_supported_compute_types("cuda"))
    except Exception:
        cuda_count = 0

    use_cuda = (req_dev in ("cuda", "gpu", "auto")) and cuda_count > 0
    if use_cuda:
        if req_comp not in ("auto", "") and req_comp in supported_cuda_types:
            comp = req_comp
        elif "float16" in supported_cuda_types:
            comp = "float16"
        elif "int8_float16" in supported_cuda_types:
            comp = "int8_float16"
        else:
            comp = "int8"
        return {
            "device": "cuda",
            "compute_type": comp,
            "cpu_threads": 0,
            "gpu_accelerated": True,
            "cuda_device_count": cuda_count,
            "label": f"NVIDIA CUDA GPU ({comp})",
        }

    threads = optimal_cpu_threads()
    comp = req_comp if req_comp not in ("auto", "", "float16") else "int8"
    return {
        "device": "cpu",
        "compute_type": comp,
        "cpu_threads": threads,
        "gpu_accelerated": False,
        "cuda_device_count": cuda_count,
        "label": f"CPU ({comp}, {threads} threads)",
    }


def get_model(
    model_name: Optional[str] = None,
    device: Optional[str] = None,
    compute_type: Optional[str] = None,
):
    """Retrieve or load a cached WhisperModel instance by configuration key."""
    info = get_model_with_info(model_name, device=device, compute_type=compute_type)
    return info[0]


def get_model_with_info(
    model_name: Optional[str] = None,
    device: Optional[str] = None,
    compute_type: Optional[str] = None,
) -> Tuple[Any, dict]:
    """Retrieve or load a cached (WhisperModel, hardware_info) tuple."""
    name = (model_name or settings.WHISPER_MODEL or "base").strip().lower()
    hw = detect_whisper_hardware(device, compute_type)
    key = f"{name}:{hw['device']}:{hw['compute_type']}:{hw['cpu_threads']}"

    with _models_lock:
        if key not in _models:
            from faster_whisper import WhisperModel
            try:
                log.info("Loading Whisper model '%s' on %s...", name, hw["label"])
                kwargs: Dict[str, Any] = {
                    "device": hw["device"],
                    "compute_type": hw["compute_type"],
                }
                if hw["device"] == "cpu" and hw["cpu_threads"] > 0:
                    kwargs["cpu_threads"] = hw["cpu_threads"]
                    kwargs["num_workers"] = 1
                model_inst = WhisperModel(name, **kwargs)
                _models[key] = (model_inst, hw)
            except Exception as exc:
                if hw["device"] == "cuda":
                    log.warning("CUDA Whisper initialization failed (%s); falling back to CPU int8", exc)
                    cpu_hw = detect_whisper_hardware("cpu", "int8")
                    cpu_key = f"{name}:cpu:{cpu_hw['compute_type']}:{cpu_hw['cpu_threads']}"
                    if cpu_key not in _models:
                        model_inst = WhisperModel(
                            name,
                            device="cpu",
                            compute_type=cpu_hw["compute_type"],
                            cpu_threads=cpu_hw["cpu_threads"],
                            num_workers=1,
                        )
                        _models[cpu_key] = (model_inst, cpu_hw)
                    return _models[cpu_key]
                raise TranscriptionError(
                    f"Could not load Whisper model '{name}' ({hw['label']}): {exc}"
                ) from exc
        return _models[key]


class TranscriptionResult(list):
    """List of segment dictionaries with attached language, hardware, and performance metadata."""

    def __init__(
        self,
        segments: List[dict],
        language: Optional[str] = None,
        language_probability: float = 0.0,
        duration: float = 0.0,
        model_name: str = "base",
        device_label: str = "CPU (int8)",
        gpu_accelerated: bool = False,
        processing_time_s: float = 0.0,
        realtime_factor: float = 0.0,
    ):
        super().__init__(segments)
        self.language = language
        self.language_probability = round(float(language_probability or 0.0), 3)
        self.duration = round(float(duration or 0.0), 3)
        self.model_name = model_name
        self.device_label = device_label
        self.gpu_accelerated = gpu_accelerated
        self.processing_time_s = round(float(processing_time_s or 0.0), 3)
        self.realtime_factor = round(float(realtime_factor or 0.0), 2)

    @property
    def segments(self) -> List[dict]:
        return list(self)

    def get(self, key: str, default=None):
        if key == "segments":
            return list(self)
        if hasattr(self, key):
            return getattr(self, key)
        return default

    def to_dict(self) -> dict:
        return {
            "segments": list(self),
            "language": self.language,
            "language_probability": self.language_probability,
            "duration": self.duration,
            "model_name": self.model_name,
            "device_label": self.device_label,
            "gpu_accelerated": self.gpu_accelerated,
            "processing_time_s": self.processing_time_s,
            "realtime_factor": self.realtime_factor,
        }


def get_wav_duration(wav_path: str) -> float:
    """Inspect WAV header without loading frames into RAM."""
    with wave.open(wav_path, "rb") as wf:
        if wf.getsampwidth() != 2 or wf.getframerate() != 16000 or wf.getnchannels() != 1:
            raise TranscriptionError("Audio must be 16 kHz mono 16-bit PCM WAV")
        return wf.getnframes() / 16000.0


def read_wav_window_float32(wav_path: str, start_sec: float, duration_sec: float) -> np.ndarray:
    """Read only the [start_sec, start_sec + duration_sec] slice of a 16 kHz mono WAV into float32 RAM."""
    with wave.open(wav_path, "rb") as wf:
        if wf.getsampwidth() != 2 or wf.getframerate() != 16000 or wf.getnchannels() != 1:
            raise TranscriptionError("Audio must be 16 kHz mono 16-bit PCM WAV")
        total_frames = wf.getnframes()
        start_frame = min(max(int(start_sec * 16000), 0), total_frames)
        max_read = max(0, total_frames - start_frame)
        n_frames = min(int(duration_sec * 16000), max_read) if duration_sec > 0 else max_read
        if n_frames <= 0:
            return np.zeros(0, dtype=np.float32)
        wf.setpos(start_frame)
        raw = wf.readframes(n_frames)
    if not raw:
        return np.zeros(0, dtype=np.float32)
    return np.frombuffer(raw, dtype=np.int16).astype(np.float32) / 32768.0


def load_wav_float32(wav_path: str) -> np.ndarray:
    """Read a 16 kHz mono 16-bit PCM WAV as float32 in [-1, 1]."""
    return read_wav_window_float32(wav_path, 0.0, 0.0)


def transcribe_audio(
    wav_path: str,
    duration: float,
    language: Optional[str] = None,
    progress_cb: Optional[Callable[[float], None]] = None,
    should_cancel: Optional[Callable[[], bool]] = None,
    model_name: Optional[str] = None,
    device: Optional[str] = None,
    compute_type: Optional[str] = None,
    *,
    telemetry_cb: Optional[Callable[[dict], None]] = None,
    checkpoint_cb: Optional[Callable[[List[dict], float], None]] = None,
    resume_from_sec: float = 0.0,
    initial_segments: Optional[List[dict]] = None,
    window_seconds: Optional[float] = None,
) -> TranscriptionResult:
    """Run windowed faster-whisper speech transcription on a 16 kHz mono WAV file.

    Processes audio in `window_seconds` (default 600s = 10-minute) streaming windows so even
    3-4 hour videos consume < 40 MB of audio buffer RAM, emit real-time progress immediately,
    and save intermediate checkpoints for crash/restart recovery.
    """
    effective_model = (model_name or settings.WHISPER_MODEL or "base").strip().lower()
    model, hw = get_model_with_info(effective_model, device=device, compute_type=compute_type)
    beam_sz = max(1, min(int(getattr(settings, "WHISPER_BEAM_SIZE", 2) or 2), 5))
    win_sec = float(window_seconds or getattr(settings, "WHISPER_CHUNK_SECONDS", 600) or 600.0)

    norm_lang = language.strip().lower() if language and language.strip() else None
    if norm_lang in ("auto", "none", "detect"):
        norm_lang = None

    try:
        wav_dur = get_wav_duration(wav_path)
        total_dur = max(float(duration or wav_dur), wav_dur, 0.001)
        out: List[dict] = list(initial_segments or [])
        start_offset = max(0.0, float(resume_from_sec or 0.0))
        if out and start_offset <= 0.0:
            start_offset = max(float(s.get("end", 0.0)) for s in out)

        detected_lang = norm_lang
        lang_prob = 1.0 if norm_lang else 0.0
        t0 = time.perf_counter()

        def _emit_telemetry(transcribed_sec: float, current_text: Optional[str] = None) -> None:
            done_s = min(max(transcribed_sec, 0.0), total_dur)
            frac = min(done_s / total_dur, 1.0)
            elapsed = max(time.perf_counter() - t0, 0.001)
            newly_done = max(done_s - start_offset, 0.01)
            rtf = newly_done / elapsed
            rem_audio = max(0.0, total_dur - done_s)
            eta_s = round(rem_audio / rtf, 1) if rtf > 0.05 else None
            if progress_cb:
                progress_cb(frac)
            if telemetry_cb:
                telemetry_cb({
                    "transcribed_seconds": round(done_s, 2),
                    "total_audio_seconds": round(total_dur, 2),
                    "progress_fraction": round(frac, 4),
                    "progress_percent": round(frac * 100.0, 1),
                    "whisper_model": effective_model,
                    "whisper_device": hw["label"],
                    "gpu_accelerated": hw["gpu_accelerated"],
                    "realtime_factor": round(rtf, 2),
                    "eta_seconds": eta_s,
                    "current_segment": (current_text or "")[:140] or None,
                })

        _emit_telemetry(start_offset)

        cur_win_start = start_offset
        while cur_win_start < wav_dur - 0.05:
            if should_cancel and should_cancel():
                raise InterruptedError("cancelled")

            nominal_end = cur_win_start + win_sec
            is_last = nominal_end >= wav_dur - 0.05
            # Read a lookahead tail so a sentence straddling the nominal boundary is transcribed whole;
            # only segments STARTING inside the nominal window are accepted, and the next window resumes
            # at the end of the last accepted segment (no truncated, lost or duplicated speech).
            cur_win_len = min(win_sec + (0.0 if is_last else BOUNDARY_LOOKAHEAD_S), wav_dur - cur_win_start)
            last_accepted_end = None
            audio_slice = read_wav_window_float32(wav_path, cur_win_start, cur_win_len)
            if audio_slice.size == 0:
                break

            segments_gen, info = model.transcribe(
                audio_slice,
                language=detected_lang,
                word_timestamps=True,
                vad_filter=True,
                beam_size=beam_sz,
                condition_on_previous_text=False,
            )

            if detected_lang is None:
                detected_lang = getattr(info, "language", None)
                lang_prob = float(getattr(info, "language_probability", 0.0) or 0.0)

            for seg in segments_gen:
                if should_cancel and should_cancel():
                    raise InterruptedError("cancelled")

                seg_start = round(cur_win_start + max(float(seg.start), 0.0), 3)
                seg_end = round(max(cur_win_start + float(seg.end), seg_start), 3)

                # Segment begins in the lookahead tail: the next window will transcribe it.
                if not is_last and seg_start >= nominal_end:
                    break

                # Prevent duplicate overlapping segments at window boundaries
                if out and seg_end <= out[-1]["end"] + 0.05:
                    continue

                words = []
                for w in (seg.words or []):
                    cleaned_word = w.word.strip()
                    if cleaned_word:
                        w_start = round(cur_win_start + max(float(w.start), 0.0), 3)
                        w_end = round(max(cur_win_start + float(w.end), w_start), 3)
                        words.append({
                            "word": cleaned_word,
                            "start": w_start,
                            "end": w_end,
                            "probability": round(min(max(float(w.probability or 0.0), 0.0), 1.0), 3),
                        })

                text = seg.text.strip()
                if not text:
                    continue

                conf = float(np.exp(seg.avg_logprob)) if seg.avg_logprob is not None else 0.0
                out.append({
                    "start": seg_start,
                    "end": seg_end,
                    "text": text,
                    "confidence": round(min(max(conf, 0.0), 1.0), 3),
                    "words": words,
                })
                last_accepted_end = seg_end
                _emit_telemetry(seg_end, text)

            if is_last:
                cur_win_end = wav_dur
            elif last_accepted_end is not None and last_accepted_end > cur_win_start + 1.0:
                cur_win_end = min(last_accepted_end, wav_dur)
            else:
                cur_win_end = min(nominal_end, wav_dur)
            _emit_telemetry(cur_win_end)
            if checkpoint_cb:
                checkpoint_cb(out, cur_win_end)
            del audio_slice
            cur_win_start = cur_win_end

        total_elapsed = max(time.perf_counter() - t0, 0.001)
        avg_rtf = max(wav_dur - start_offset, 0.0) / total_elapsed
        _emit_telemetry(total_dur)

        return TranscriptionResult(
            segments=out,
            language=detected_lang or "en",
            language_probability=lang_prob or 1.0,
            duration=wav_dur,
            model_name=effective_model,
            device_label=hw["label"],
            gpu_accelerated=hw["gpu_accelerated"],
            processing_time_s=total_elapsed,
            realtime_factor=avg_rtf,
        )

    except InterruptedError:
        raise
    except TranscriptionError:
        raise
    except Exception as exc:
        raise TranscriptionError(f"Transcription failed: {exc}") from exc


def compute_energy(wav_path: str, window: float = 0.5) -> List[float]:
    """Streamed RMS loudness per `window` seconds from a 16-bit mono WAV (constant < 1 MB RAM)."""
    with wave.open(wav_path, "rb") as wf:
        rate, n = wf.getframerate(), wf.getnframes()
        if wf.getsampwidth() != 2 or n == 0:
            return []
        step = max(int(rate * window), 1)
        out: List[float] = []
        while True:
            raw = wf.readframes(step)
            if not raw:
                break
            samples = np.frombuffer(raw, dtype=np.int16).astype(np.float64)
            out.append(float(np.sqrt(np.mean(samples ** 2))) / 32768.0 if samples.size else 0.0)
        return [round(v, 5) for v in out]
