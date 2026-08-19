# ربات live در همین ترمینال — خروجی را می‌بینی (ترمینال را نبند)
$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot
Set-Location $Root

Write-Host "Stopping background daemon (if any)..." -ForegroundColor Yellow
& "$PSScriptRoot\stop_live_daemon.ps1"

Write-Host "Starting live bot in THIS terminal (Ctrl+C to stop)..." -ForegroundColor Green
python -m tradingbot --loop --execute
