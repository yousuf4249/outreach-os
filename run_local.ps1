# Weblinx Outreach OS - Local PowerShell Runner
Write-Host "==========================================================" -ForegroundColor Cyan
Write-Host "  Weblinx Outreach OS - Local Development Server" -ForegroundColor Cyan
Write-Host "  Company: Weblinx Solution (https://weblinxsolution.com)" -ForegroundColor DarkCyan
Write-Host "==========================================================" -ForegroundColor Cyan

$env:DATABASE_URL = "sqlite+aiosqlite:///local_dev.db"
$env:BASE_URL = "http://localhost:8000"
$env:QUICKLY_SECRET_KEY = "weblinx_local_secret_key_2026"
$env:QUICKLY_LOCAL_DISK_BACKUPS = "1"

$pythonPath = (Get-Command python -ErrorAction SilentlyContinue)?.Source
if (-not $pythonPath) {
    $pythonPath = "$env:USERPROFILE\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe"
}

Write-Host "`nStarting Frontend dev server..." -ForegroundColor Yellow
Start-Process "cmd.exe" -ArgumentList "/k", "npm.cmd --prefix frontend run dev -- --host 127.0.0.1 --port 5173" -WindowStyle Normal

Write-Host "Starting Backend dev server on http://localhost:8000..." -ForegroundColor Green
Write-Host "Opening browser: http://localhost:5173" -ForegroundColor Yellow
Start-Process "http://localhost:5173"

& $pythonPath -m uvicorn app.main:app --host 127.0.0.1 --port 8000 --reload
