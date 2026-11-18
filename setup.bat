@echo off
setlocal EnableExtensions EnableDelayedExpansion

REM ============================================================================
REM ViralClip AI -- Windows 11 Setup and Verification Script
REM Usage:
REM   setup.bat              Interactive full setup
REM   setup.bat --verify     Non-interactive dependency and environment check
REM ============================================================================

cd /d "%~dp0"

set "NON_INTERACTIVE=0"
if /I "%~1"=="--verify" set "NON_INTERACTIVE=1"
if /I "%~1"=="--non-interactive" set "NON_INTERACTIVE=1"

echo ============================================================================
echo   ViralClip AI -- Windows 11 Environment Setup
echo ============================================================================
echo.

REM 1. Check Python
echo [1/7] Checking Python installation...
where python >nul 2>&1
if errorlevel 1 (
    echo [ERROR] Python was not found in PATH.
    echo         Install Python 3.10+ from https://www.python.org/downloads/
    echo         and check "Add python.exe to PATH" during installation.
    exit /b 1
)
for /f "tokens=*" %%i in ('python --version 2^>^&1') do echo         Found %%i

REM 2. Create or verify Python virtual environment (.venv)
echo [2/7] Configuring Python virtual environment (.venv)...
if not exist ".venv\Scripts\python.exe" (
    echo         Creating virtual environment in .venv...
    python -m venv .venv
    if errorlevel 1 (
        echo [ERROR] Failed to create Python virtual environment.
        exit /b 1
    )
) else (
    echo         Existing .venv found.
)

REM 3. Install/verify backend Python dependencies
echo [3/7] Verifying backend Python dependencies...
if "%NON_INTERACTIVE%"=="0" (
    ".venv\Scripts\python.exe" -m pip install --upgrade pip --quiet
    ".venv\Scripts\python.exe" -m pip install -r backend\requirements.txt --quiet
    if errorlevel 1 (
        echo [ERROR] Failed to install Python dependencies from backend\requirements.txt.
        exit /b 1
    )
)
".venv\Scripts\python.exe" -c "import fastapi, uvicorn, sqlalchemy, aiosqlite, faster_whisper, cv2, numpy, httpx; print('        Backend Python packages verified OK.')"
if errorlevel 1 (
    echo [ERROR] Missing required Python packages in .venv. Run setup.bat without --verify.
    exit /b 1
)

REM 4. Check Node.js & npm and install frontend dependencies
echo [4/7] Checking Node.js and frontend dependencies...
where node >nul 2>&1
if errorlevel 1 (
    echo [ERROR] Node.js was not found in PATH.
    echo         Install Node.js 18+ LTS from https://nodejs.org/
    exit /b 1
)
for /f "tokens=*" %%i in ('node --version 2^>^&1') do echo         Found Node.js %%i

if not exist "frontend\node_modules" (
    echo         Installing frontend npm packages...
    call npm --prefix frontend install
    if errorlevel 1 (
        echo [ERROR] npm install failed in frontend directory.
        exit /b 1
    )
) else (
    echo         Frontend node_modules present.
)

REM 5. Configure .env and storage directories (never overwrite existing .env)
echo [5/7] Configuring .env and local storage directories...
if not exist ".env" (
    if exist ".env.example" (
        copy /Y ".env.example" ".env" >nul
        echo         Created .env from .env.example ^(no API secrets included^).
    )
) else (
    echo         Existing .env preserved.
)

if not exist "storage\temp" mkdir "storage\temp"
if not exist "storage\output" mkdir "storage\output"
if not exist "storage\db" mkdir "storage\db"
echo         Verified storage\temp, storage\output, and storage\db.

REM 6. Verify FFmpeg, FFprobe, and Hardware/CPU Encoders
echo [6/7] Verifying FFmpeg, FFprobe, and H.264 encoders...
".venv\Scripts\python.exe" -c "from backend.app.gpu_config import detect_encoders; d = detect_encoders(); assert d['ffmpeg'] and d['ffprobe'], 'FFmpeg or FFprobe not found'; print('        FFmpeg :', d['ffmpeg']); print('        FFprobe:', d['ffprobe']); print('        Encoder:', d['selected']['label'] if d['selected'] else 'None')"
if errorlevel 1 (
    echo [WARNING] FFmpeg or FFprobe was not detected.
    echo           Install FFmpeg on Windows 11 with:  winget install Gyan.FFmpeg
    echo           or set FFMPEG_PATH and FFPROBE_PATH in .env.
    exit /b 1
)

REM 7. Verify SQLite database initialization & schema migration
echo [7/7] Verifying SQLite database and schema migration...
".venv\Scripts\python.exe" -c "from backend.app import job_runner; res = job_runner.preflight_sync(); print('        SQLite database initialized OK:', res)"
if errorlevel 1 (
    echo [ERROR] SQLite initialization failed.
    exit /b 1
)

echo.
echo ============================================================================
echo   Setup Complete! Run start.bat to launch ViralClip AI.
echo ============================================================================
if "%NON_INTERACTIVE%"=="0" pause
exit /b 0
