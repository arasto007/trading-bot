# Phase 47C — 5-day forward demo validation (MT5 demo, live execution ON).
$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot
$Logs = Join-Path $Root "logs"
$Phase47c = Join-Path $Logs "phase47c"
New-Item -ItemType Directory -Force -Path $Phase47c | Out-Null

Push-Location $Root

# Phase 47B PA-primary engine
$env:USE_ML_KERNEL = "false"
$env:ENABLE_ML_SHADOW = "true"
$env:MULTI_ENGINE_ROUTER_ENABLED = "true"
$env:ADAPTIVE_REGIME_ENABLED = "false"
$env:VOL_REGIME_ENABLED = "false"
$env:META_LABEL_THRESHOLD = "0.38"

# Phase 47C forward demo tracking
$env:PHASE47C_FORWARD_DEMO = "true"

# Live execution on demo account (not dry-run)
$env:TRADINGBOT_DRY_RUN = ""
Remove-Item Env:TRADINGBOT_DRY_RUN -ErrorAction SilentlyContinue

Write-Host "Phase 47C forward demo — starting live watchdog (--execute, demo only)"
Write-Host "Metrics: logs/phase47c/daily_YYYY-MM-DD.json"
Write-Host "Certification: python logs/phase47c_forward_demo_validation.py"

& python logs/phase47c_forward_demo_validation.py --reset
& powershell -File (Join-Path $Root "scripts\start_live_daemon.ps1")
Pop-Location
