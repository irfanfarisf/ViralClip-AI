@echo off
setlocal EnableExtensions EnableDelayedExpansion

REM ============================================================================
REM ViralClip AI -- Windows 11 Startup and Lifecycle Script
REM Usage:
REM   start.bat            Start backend (port 8000) and frontend (port 5173)
REM   start.bat --check    Run pre-flight startup verification and exit
REM   start.bat --stop     Stop running backend and frontend servers
REM ============================================================================

cd /d "%~dp0"

if /I "%~1"=="--stop" goto :STOP_SERVERS

echo ============================================================================
echo   ViralClip AI -- Starting Local Application
echo ============================================================================

REM 1. Verify Python virtual environment
if not exist ".venv\Scripts\python.exe" (
    echo [ERROR] Python virtual environment not found at .venv\Scripts\python.exe
    echo         Please run setup.bat first.
    exit /b 1
)

REM 2. Ensure .env and storage directories exist (never deletes existing files)
if not exist ".env" (
    if exist ".env.example" (
        copy /Y ".env.example" ".env" >nul
        echo [INFO] Created .env from .env.example
    )
)
if not exist "storage\temp" mkdir "storage\temp"
if not exist "storage\output" mkdir "storage\output"
if not exist "storage\db" mkdir "storage\db"

REM 3. Run pre-flight check (FFmpeg + SQLite schema + interrupted job recovery + safe temp cleanup)
echo [1/3] Running pre-flight checks ^(FFmpeg, SQLite, safe cleanup^)...
".venv\Scripts\python.exe" -c "from backend.app.gpu_config import find_ffmpeg, find_ffprobe; from backend.app import job_runner; assert find_ffmpeg() and find_ffprobe(), 'FFmpeg/FFprobe missing'; res = job_runner.preflight_sync(); print('      Pre-flight OK:', res)"
if errorlevel 1 (
    echo [ERROR] Pre-flight check failed. Run setup.bat to diagnose.
    exit /b 1
)

if /I "%~1"=="--check" (
    echo [OK] Pre-flight startup check passed.
    exit /b 0
)

REM 4. Launch FastAPI Backend (http://127.0.0.1:8000)
echo [2/3] Starting FastAPI Backend on http://127.0.0.1:8000 ...
start "ViralClip AI Backend" cmd /k "cd /d "%~dp0" && ".venv\Scripts\python.exe" -m uvicorn backend.app.main:app --host 127.0.0.1 --port 8000"

REM 5. Launch Vite React Frontend (http://localhost:5173)
echo [3/3] Starting React Frontend on http://localhost:5173 ...
start "ViralClip AI Frontend" cmd /k "cd /d "%~dp0\frontend" && npm run dev -- --host 127.0.0.1 --port 5173"

echo.
echo ============================================================================
echo   ViralClip AI is starting!
echo   - Frontend UI : http://localhost:5173
echo   - Backend API : http://127.0.0.1:8000
echo   - API Docs    : http://127.0.0.1:8000/docs
echo   - Health Check: http://127.0.0.1:8000/api/health
echo   - To Stop     : start.bat --stop  (or close the two terminal windows)
echo ============================================================================
exit /b 0

:STOP_SERVERS
echo Stopping ViralClip AI servers on ports 8000 and 5173...
for %%P in (8000 5173) do (
    for /f "tokens=5" %%A in ('netstat -ano ^| findstr /R /C:":%%P .*LISTENING"') do (
        if not "%%A"=="0" (
            echo   Terminating PID %%A on port %%P...
            taskkill /F /PID %%A >nul 2>&1
        )
    )
)
echo Done.
exit /b 0
