# ViralClip AI — Local-First AI Vertical Video Studio (Windows 11)

ViralClip AI transforms long-form gameplay, livestreams, and commentary videos into vertical **9:16 (1080×1920)** short-form clips with **Faster-Whisper word-level transcription**, **AI/rule-based highlight detection**, **dynamic OpenCV smart cropping**, **animated `.ass` word-by-word subtitles**, **hardware GPU encoding (NVIDIA NVENC / Intel QSV / AMD AMF with CPU fallback)**, and **grounded YouTube Shorts metadata generation**.

---

## 1. System Requirements (Windows 11)

| Component | Requirement | Notes |
| :--- | :--- | :--- |
| **Operating System** | Windows 11 (64-bit) | Local-first; no cloud account required |
| **Python** | Python 3.10 – 3.14 | With `venv` and `pip` enabled |
| **Node.js** | Node.js 18+ LTS & `npm` | For the React 19 + Vite + Tailwind CSS studio UI |
| **FFmpeg & FFprobe** | FFmpeg 6.0+ (Full build) | Install via `winget install Gyan.FFmpeg` or place in `tools/` |
| **GPU (Optional)** | NVIDIA (NVENC), Intel (QSV), or AMD (AMF) | Verified via real 1-frame encode; automatically falls back to `libx264` CPU |

---

## 2. Quick Start on Windows 11

### Step 1 — Run First-Time Setup
Open **Command Prompt** or **PowerShell** in the project root directory and run:

```cmd
setup.bat
```

`setup.bat` performs the following:
1. Verifies Python and creates the local `.venv` virtual environment.
2. Installs backend dependencies from `backend\requirements.txt`.
3. Verifies Node.js and installs frontend packages in `frontend\node_modules`.
4. Creates `.env` from `.env.example` (if `.env` does not already exist) without overwriting user settings.
5. Creates local storage directories (`storage\temp`, `storage\output`, `storage\db`).
6. Verifies `ffmpeg.exe`, `ffprobe.exe`, and probes available hardware/CPU H.264 encoders.
7. Initializes the SQLite database (`storage\db\viralclip.db`) and runs schema migrations.

To run a non-interactive verification check at any time:
```cmd
setup.bat --verify
```

---

### Step 2 — Start ViralClip AI
```cmd
start.bat
```

`start.bat` runs pre-flight checks (FFmpeg, SQLite schema migration, interrupted job recovery, and safe temporary-file cleanup) and opens two console windows:
- **Frontend Studio UI:** `http://localhost:5173`
- **FastAPI Backend:** `http://127.0.0.1:8000`
- **Interactive API Docs:** `http://127.0.0.1:8000/docs`
- **Health & Encoder Status:** `http://127.0.0.1:8000/api/health`

To run pre-flight startup checks without launching windows:
```cmd
start.bat --check
```

---

### Step 3 — Stop ViralClip AI
```cmd
start.bat --stop
```
Or close the **ViralClip AI Backend** and **ViralClip AI Frontend** terminal windows.

---

## 3. Manual PowerShell / CMD Commands

### Install Dependencies Manually
```powershell
# 1. Create Python virtual environment and install backend packages
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install --upgrade pip
.\.venv\Scripts\python.exe -m pip install -r backend\requirements.txt

# 2. (Optional) Install yt-dlp for authorized YouTube/Twitch URL imports
.\.venv\Scripts\python.exe -m pip install -r backend\requirements-optional.txt

# 3. Install frontend packages and verify build
npm --prefix frontend install
npm --prefix frontend run build
```

### Start Backend & Frontend Manually
```powershell
# Terminal 1 — Start FastAPI Backend (Port 8000)
.\.venv\Scripts\python.exe -m uvicorn backend.app.main:app --host 127.0.0.1 --port 8000

# Terminal 2 — Start Vite Frontend (Port 5173)
npm --prefix frontend run dev -- --host 127.0.0.1 --port 5173
```

---

## 4. Environment Configuration & API Credential Protection

Configuration is read from `.env` (copied from `.env.example`).
- **Local-First Operation:** ViralClip AI works 100% offline using local `faster-whisper` transcription, deterministic highlight detection, and local rule-based Shorts metadata generation.
- **Credential Protection:**
  - `.env` is listed in `.gitignore` and is never committed to version control.
  - Optional `GEMINI_API_KEY` and `OPENAI_API_KEY` entered in the UI Settings page are held in memory only (`AppContext`) and are never written to `localStorage`.

Key settings in `.env`:
```ini
HOST=127.0.0.1
PORT=8000
CORS_ORIGINS=["http://localhost:5173","http://127.0.0.1:5173"]

STORAGE_DIR=./storage
TEMP_DIR=./storage/temp
OUTPUT_DIR=./storage/output
DB_PATH=./storage/db/viralclip.db

WHISPER_MODEL=base
WHISPER_DEVICE=cpu
WHISPER_COMPUTE_TYPE=int8
```

---

## 5. Storage Architecture & Safe Cleanup Policy

- `storage/temp/<video_id>/source.<ext>` — Uploaded user source videos (preserved until the user deletes the project).
- `storage/temp/<video_id>/_work/` — Temporary scratch directory for extracted `audio.wav` during analysis (deleted immediately after analysis completes).
- `storage/output/<clip_id>/<title>_<clip_id>.mp4` — Rendered 1080×1920 H.264/AAC vertical MP4 exports (preserved until the user deletes the project).
- `storage/db/viralclip.db` — Local SQLite database storing videos, jobs, word-level transcripts, clips, and Shorts metadata.

### Safe Temporary-File Cleanup
Cleanup runs automatically on startup, every `CLEANUP_INTERVAL_MINUTES` (default 30 min), and on demand via `POST /api/health/cleanup`:
- **Never deletes** any video registered in the `videos` table or any completed `.mp4` export in `storage/output/`.
- Removes only stale orphaned upload folders, leftover `_work` scratch directories, incomplete `*.part.mp4` files, and temporary `render_*` subtitle folders older than 1 hour.

---

## 6. Windows 11 Troubleshooting Guide

### 1. FFmpeg or FFprobe Not Found
- **Symptom:** `/api/health` shows `"ffmpeg": false` or `setup.bat` reports FFmpeg missing.
- **Fix:**
  1. Install FFmpeg via Winget:
     ```powershell
     winget install Gyan.FFmpeg
     ```
  2. Or set explicit paths in `.env`:
     ```ini
     FFMPEG_PATH=C:/ffmpeg/bin/ffmpeg.exe
     FFPROBE_PATH=C:/ffmpeg/bin/ffprobe.exe
     ```

### 2. Port 8000 or 5173 Already in Use
- **Symptom:** `ERROR: [Errno 10048] error while attempting to bind on address ('127.0.0.1', 8000)`.
- **Fix:** Run `start.bat --stop` or check active PIDs in PowerShell:
  ```powershell
  netstat -ano | findstr ":8000 :5173"
  taskkill /F /PID <PID>
  ```

### 3. Interrupted Jobs After Restart
- **Symptom:** The backend or PC was closed while a video was mid-analysis or mid-export.
- **Behavior:** On startup, `recover_interrupted()` automatically marks interrupted jobs as `failed` (`"Interrupted by a backend restart. Press Restart to run it again."`) so they never remain stuck at a frozen progress bar. Click **Restart** in the Processing page to resume cleanly.

### 4. Hardware GPU Encoding Falls Back to CPU
- **Symptom:** Export uses `CPU (libx264)` instead of NVENC/QSV/AMF.
- **Explanation:** `gpu_config.py` runs an actual 1-frame FFmpeg hardware encode test (`h264_nvenc`, `h264_qsv`, `h264_amf`). If GPU drivers are outdated or unsupported by FFmpeg, it transparently falls back to `libx264` and reports `"gpu_accelerated": false`. Update your NVIDIA/AMD/Intel graphics driver to enable hardware encoding.

### 5. YouTube / Twitch URL Import Returns HTTP 503
- **Symptom:** Importing a URL displays `"yt-dlp is not installed on the server"`.
- **Fix:** Install the optional `yt-dlp` package into `.venv`:
  ```powershell
  .\.venv\Scripts\python.exe -m pip install -r backend\requirements-optional.txt
  ```

---

## 7. Running Automated Tests

```powershell
# Run backend unit tests (37 tests)
.\.venv\Scripts\python.exe -m unittest backend/tests/unit/test_backend_units.py

# Run full end-to-end smoke test suite (75 checks against live Uvicorn + FFmpeg + Whisper)
.\.venv\Scripts\python.exe backend/tests/e2e_smoke.py
```
