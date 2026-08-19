# Phase 51A - Real forward demo certification (MT5 demo, PA+Meta, live execution ON).
$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot
$Logs = Join-Path $Root "logs"
$Phase51a = Join-Path $Logs "phase51a"
New-Item -ItemType Directory -Force -Path $Phase51a | Out-Null

Push-Location $Root

# Phase 50A PA production lock + Phase 47B PA-primary engine
$env:PA_PRODUCTION_LOCK = "true"
$env:USE_ML_KERNEL = "false"
$env:ENABLE_ML_SHADOW = "true"
$env:MULTI_ENGINE_ROUTER_ENABLED = "true"
$env:ADAPTIVE_REGIME_ENABLED = "false"
$env:VOL_REGIME_ENABLED = "false"
$env:META_LABEL_THRESHOLD = "0.38"
$env:PHASE52A_PM = "false"

# Phase 51A forward demo certification tracking
$env:PHASE51A_FORWARD_DEMO = "true"

# Live execution on demo account (not dry-run)
$env:TRADINGBOT_DRY_RUN = ""
Remove-Item Env:TRADINGBOT_DRY_RUN -ErrorAction SilentlyContinue

Write-Host "Phase 51A forward demo - starting live watchdog (execute mode, demo only)"
Write-Host "Trade log: logs/phase51a/trades.jsonl"
Write-Host "Daily reports: logs/phase51a/daily_YYYY-MM-DD.json"
Write-Host "Certification: python logs/phase51a_forward_demo_certification.py"

& python logs/phase51a_forward_demo_certification.py --reset
& powershell -File (Join-Path $Root "scripts\start_live_daemon.ps1")
Pop-Location
