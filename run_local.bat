@echo off
title Weblinx Outreach OS - Local Server
echo ==========================================================
echo   Weblinx Outreach OS - Local Development Server
echo   Company: Weblinx Solution (https://weblinxsolution.com)
echo ==========================================================
echo.

set "DATABASE_URL=sqlite+aiosqlite:///local_dev.db"
set "BASE_URL=http://localhost:8000"
set "QUICKLY_SECRET_KEY=weblinx_local_secret_key_2026"
set "QUICKLY_LOCAL_DISK_BACKUPS=1"

REM Find python executable
where python >nul 2>nul
if %ERRORLEVEL% equ 0 (
    set "PY_CMD=python"
) else (
    set "PY_CMD=%USERPROFILE%\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe"
)

echo Using Python: %PY_CMD%
echo.
echo Starting Frontend (Vite) on http://localhost:5173 ...
start "Weblinx Frontend (Vite)" cmd /k "npm.cmd --prefix frontend run dev -- --host 127.0.0.1 --port 5173"

echo Starting Backend (FastAPI / Uvicorn) on http://localhost:8000 ...
echo.
echo [1] Open Frontend in Browser: http://localhost:5173
echo [2] Open Swagger API Docs:   http://localhost:8000/docs
echo.
echo Login Credentials:
echo   Username: admin  (or admin@weblinxsolution.com)
echo   Password: Admin123!
echo.
echo Press Ctrl+C in this window to stop the backend.
echo ==========================================================
echo.

"%PY_CMD%" -m uvicorn app.main:app --host 127.0.0.1 --port 8000 --reload
pause
