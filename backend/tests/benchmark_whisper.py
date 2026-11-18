"""Measured Whisper pipeline benchmark (audio extraction + faster-whisper) on this machine.

Usage:  .venv\\Scripts\\python.exe backend/tests/benchmark_whisper.py 10 30 --model base
Builds a 1280x720 MP4 of N minutes whose audio is the real speech fixture (backend/tests/fixtures/speech.wav)
looped, extracts audio with the production extractor, transcribes with the production transcriber and
reports wall time, RTF, CPU utilisation, peak RAM and transcript sanity checks.
NOTE: looped fixture audio => quality checks measure consistency/coverage, not general accuracy.
GPU: reported from CTranslate2 (device count). No GPU utilisation is claimed unless CUDA is really used.
"""
import argparse
import ctypes
import json
import re
import subprocess
import sys
import time
from ctypes import wintypes
from difflib import SequenceMatcher
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from backend.app import transcription  # noqa: E402
from backend.app.gpu_config import find_ffmpeg  # noqa: E402
from backend.app.video_processor import extract_audio_wav  # noqa: E402

FIX = ROOT / "backend" / "tests" / "fixtures" / "speech.wav"
WORK = ROOT / "storage" / "bench"


class _PMC(ctypes.Structure):
    _fields_ = [("cb", wintypes.DWORD), ("PageFaultCount", wintypes.DWORD),
                ("PeakWorkingSetSize", ctypes.c_size_t), ("WorkingSetSize", ctypes.c_size_t),
                ("QuotaPeakPagedPoolUsage", ctypes.c_size_t), ("QuotaPagedPoolUsage", ctypes.c_size_t),
                ("QuotaPeakNonPagedPoolUsage", ctypes.c_size_t), ("QuotaNonPagedPoolUsage", ctypes.c_size_t),
                ("PagefileUsage", ctypes.c_size_t), ("PeakPagefileUsage", ctypes.c_size_t)]


def peak_ram_mb() -> float:
    pmc = _PMC()
    pmc.cb = ctypes.sizeof(pmc)
    h = ctypes.windll.kernel32.GetCurrentProcess()
    k32 = ctypes.WinDLL("kernel32", use_last_error=True)
    k32.GetCurrentProcess.restype = wintypes.HANDLE
    psapi = ctypes.WinDLL("psapi", use_last_error=True)
    psapi.GetProcessMemoryInfo.argtypes = [wintypes.HANDLE, ctypes.POINTER(_PMC), wintypes.DWORD]
    psapi.GetProcessMemoryInfo.restype = wintypes.BOOL
    if not psapi.GetProcessMemoryInfo(k32.GetCurrentProcess(), ctypes.byref(pmc), pmc.cb):
        raise ctypes.WinError(ctypes.get_last_error())
    return pmc.PeakWorkingSetSize / 2**20


def norm(t: str) -> str:
    return re.sub(r"[^a-z0-9 ]", "", t.lower())


def build_video(minutes: int) -> Path:
    WORK.mkdir(parents=True, exist_ok=True)
    out = WORK / f"bench_{minutes}min.mp4"
    if out.exists():
        return out
    ff = find_ffmpeg()
    secs = minutes * 60
    subprocess.run([ff, "-y", "-loglevel", "error", "-f", "lavfi", "-i", f"testsrc2=s=1280x720:r=5:d={secs}",
                    "-stream_loop", "-1", "-i", str(FIX), "-t", str(secs), "-map", "0:v", "-map", "1:a",
                    "-c:v", "libx264", "-preset", "ultrafast", "-crf", "35", "-pix_fmt", "yuv420p",
                    "-c:a", "aac", "-b:a", "96k", str(out)], check=True)
    return out


def run(minutes: int, model: str) -> dict:
    video = build_video(minutes)
    wav = WORK / f"bench_{minutes}min.wav"
    wav.unlink(missing_ok=True)
    t = time.perf_counter()
    extract_audio_wav(str(video), str(wav), duration=minutes * 60, reuse_cached=False)
    t_extract = time.perf_counter() - t

    tel = []
    cpu0, wall0 = time.process_time(), time.perf_counter()
    t_load = time.perf_counter()
    transcription.get_model_with_info(model)  # load once, timed separately
    t_load = time.perf_counter() - t_load
    cpu0, wall0 = time.process_time(), time.perf_counter()
    res = transcription.transcribe_audio(str(wav), minutes * 60, language="en", model_name=model,
                                         telemetry_cb=lambda d: tel.append(d))
    wall = time.perf_counter() - wall0
    cpu = time.process_time() - cpu0
    segs = list(res)
    # sanity checks
    mono = all(segs[i]["start"] <= segs[i]["end"] and (i == 0 or segs[i]["start"] >= segs[i - 1]["start"])
               for i in range(len(segs)))
    overlaps = sum(1 for i in range(1, len(segs)) if segs[i]["start"] < segs[i - 1]["end"] - 0.25)
    gaps = [segs[i]["start"] - segs[i - 1]["end"] for i in range(1, len(segs))]
    covered = sum(s["end"] - s["start"] for s in segs)
    loop = 31.1756
    per_loop = {}
    for s in segs:
        per_loop.setdefault(int(s["start"] // loop), []).append(norm(s["text"]))
    texts = {k: " ".join(v) for k, v in per_loop.items()}
    ref = texts.get(1) or texts.get(0, "")
    sims = [SequenceMatcher(None, ref, v).ratio() for k, v in texts.items() if 0 < k < max(texts)]
    pct = [d["progress_percent"] for d in tel]
    return {
        "minutes": minutes, "model": model, "device": res.device_label, "gpu_accelerated": res.gpu_accelerated,
        "extract_s": round(t_extract, 1), "model_load_s": round(t_load, 1),
        "transcribe_s": round(wall, 1), "rtf_x_realtime": round(minutes * 60 / wall, 2),
        "avg_cpu_cores_busy": round(cpu / wall, 2), "peak_ram_mb": round(peak_ram_mb()),
        "segments": len(segs), "words": sum(len(s["words"]) for s in segs),
        "speech_coverage_pct": round(100 * covered / (minutes * 60), 1),
        "monotonic": mono, "overlaps": overlaps, "max_gap_s": round(max(gaps), 1) if gaps else 0,
        "telemetry_updates": len(tel), "progress_monotonic": pct == sorted(pct),
        "loop_text_similarity_mean": round(sum(sims) / len(sims), 3) if sims else None,
        "loop_text_similarity_min": round(min(sims), 3) if sims else None,
        "language": res.language,
    }


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("minutes", type=int, nargs="+")
    ap.add_argument("--model", default="base")
    a = ap.parse_args()
    for m in a.minutes:
        print(json.dumps(run(m, a.model)), flush=True)
