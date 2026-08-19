# Phase 6A — 30-day forward demo certification (PA+Meta, ML shadow only).

$ErrorActionPreference = "Stop"

$Root = Split-Path -Parent $PSScriptRoot

$Logs = Join-Path $Root "logs"

$Phase6a = Join-Path $Logs "phase6a"

New-Item -ItemType Directory -Force -Path $Phase6a | Out-Null



Push-Location $Root



# Phase 6A production profile

$env:PA_PRODUCTION_LOCK = "true"

$env:USE_ML_KERNEL = "false"

$env:ENABLE_ML_SHADOW = "true"

$env:MULTI_ENGINE_ROUTER_ENABLED = "true"

$env:ADAPTIVE_REGIME_ENABLED = "false"

$env:VOL_REGIME_ENABLED = "false"

$env:ADAPTIVE_QUALITY_ENGINE = "false"

$env:PHASE52A_PM = "false"

$env:META_LABEL_THRESHOLD = "0.38"



# Forward demo tracking (shared Phase 51A trade log)

$env:PHASE51A_FORWARD_DEMO = "true"

$env:PHASE6A_FORWARD_DEMO = "true"



Remove-Item Env:TRADINGBOT_DRY_RUN -ErrorAction SilentlyContinue



Write-Host "Phase 6A — 30-day forward demo certification"

Write-Host "Daily rollup: python logs/phase6a_final_production_certification.py"

Write-Host "Preflight:    python logs/phase6a_final_production_certification.py --preflight"



& python logs/phase6a_final_production_certification.py --preflight

if ($LASTEXITCODE -ne 0) {

    Write-Warning "Preflight failed — fix MT5/demo before starting forward demo"

}



& powershell -File (Join-Path $Root "scripts\start_live_daemon.ps1")

Pop-Location

