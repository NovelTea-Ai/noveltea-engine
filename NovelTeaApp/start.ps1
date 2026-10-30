# NovelTea Engine startup script
# Run from NovelTeaApp directory: .\start.ps1

$ErrorActionPreference = "Stop"
$root = $PSScriptRoot
$python = Join-Path $root ".venv\Scripts\python.exe"
if (-not (Test-Path $python)) {
    $python = "python"
}
$npm = "npm"
if (-not (Get-Command $npm -ErrorAction SilentlyContinue)) {
    $npm = "C:\Program Files\nodejs\npm.cmd"
}

Write-Host ""
Write-Host "  NovelTea Engine - Starting..." -ForegroundColor Cyan
Write-Host ""

# Start FastAPI backend
Write-Host "  [1/2] Starting backend (port 7432)..." -ForegroundColor Yellow
$backend = Start-Process -FilePath $python `
    -ArgumentList "main.py" `
    -WorkingDirectory "$root\backend" `
    -PassThru -WindowStyle Minimized

Write-Host "        Backend PID: $($backend.Id)" -ForegroundColor DarkGray

# Give backend a moment
Start-Sleep -Seconds 2

# Test backend is up
try {
    $r = Invoke-WebRequest -Uri "http://127.0.0.1:7432/api/health" -UseBasicParsing -TimeoutSec 5
    Write-Host "        Backend online" -ForegroundColor Green
} catch {
    Write-Host "        Backend may still be starting..." -ForegroundColor Yellow
}

# Start Vite dev server
Write-Host "  [2/2] Starting UI (port 5173)..." -ForegroundColor Yellow
$renderer = Start-Process -FilePath $npm `
    -ArgumentList "run", "dev" `
    -WorkingDirectory "$root\renderer" `
    -PassThru -WindowStyle Minimized

Write-Host "        Renderer PID: $($renderer.Id)" -ForegroundColor DarkGray

Start-Sleep -Seconds 3

Write-Host ""
Write-Host "  NovelTea Engine is running!" -ForegroundColor Green
Write-Host "  UI:      http://localhost:5173" -ForegroundColor Cyan
Write-Host "  API:     http://127.0.0.1:7432" -ForegroundColor Cyan
Write-Host "  API Docs: http://127.0.0.1:7432/docs" -ForegroundColor Cyan
Write-Host ""
Write-Host "  Opening browser..." -ForegroundColor DarkGray
Start-Process "http://localhost:5173"

Write-Host ""
Write-Host "  Press Enter to stop both servers." -ForegroundColor Yellow
Read-Host

Write-Host "  Stopping..." -ForegroundColor Red
Stop-Process -Id $backend.Id -Force -ErrorAction SilentlyContinue
Stop-Process -Id $renderer.Id -Force -ErrorAction SilentlyContinue
Write-Host "  Done." -ForegroundColor Green
