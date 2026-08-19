# Restart MT5 so common.ini Experts changes apply, then enable Algo Trading.
$ErrorActionPreference = "Stop"
$Root = if ($PSScriptRoot) { Split-Path -Parent $PSScriptRoot } else { "C:\Users\AMIR\Desktop\TradingBot new" }

function Invoke-Diagnose {
    Push-Location $Root
    & python scripts/diagnose_autotrading.py --attach-only 2>&1 | Out-String | Write-Host
    $code = $LASTEXITCODE
    Pop-Location
    return $code
}

function Wait-Mt5Login {
    param([int]$MaxSec = 90)
    Push-Location $Root
    & python scripts/wait_mt5_login.py --timeout $MaxSec
    $ok = ($LASTEXITCODE -eq 0)
    Pop-Location
    return $ok
}

Write-Host "=== Restart MT5 (apply ini + Algo Trading) ==="

Push-Location $Root
$termPath = (& python -c "from tradingbot.config.dotenv_loader import load_dotenv; load_dotenv(); from tradingbot.adapters.legacy_loader import load_legacy_config; from tradingbot.adapters.mt5_utils import discover_terminal_path; print(discover_terminal_path(load_legacy_config()) or '')").Trim()
Pop-Location

if (-not $termPath -or -not (Test-Path $termPath)) {
    $termPath = "C:\Program Files\MetaTrader 5\terminal64.exe"
}
Write-Host "terminal: $termPath"

Get-Process terminal64 -ErrorAction SilentlyContinue | ForEach-Object {
    Write-Host "Stopping MT5 PID $($_.Id)..."
    Stop-Process -Id $_.Id -Force -ErrorAction SilentlyContinue
}
Start-Sleep -Seconds 4

Write-Host "Starting MT5..."
Start-Process -FilePath $termPath
Start-Sleep -Seconds 12

$proc = Get-Process terminal64 -ErrorAction SilentlyContinue | Select-Object -First 1
if (-not $proc) {
    Write-Host "FAIL: MT5 did not start"
    exit 1
}
Write-Host "MT5 PID $($proc.Id) - waiting for login..."
if (-not (Wait-Mt5Login -MaxSec 90)) {
    Write-Host "WARN: login not confirmed yet - continuing anyway"
}

Write-Host "Enable AutoTrading (Win32 + Options)..."
Push-Location $Root
& python scripts/enable_mt5_autotrading.py --pid $proc.Id
$enableRc = $LASTEXITCODE
Pop-Location

if ($enableRc -ne 0) {
    Write-Host "WARN: auto-enable partial - running diagnose..."
}

if ((Invoke-Diagnose) -eq 0) {
    Write-Host "AutoTrading OK"
    exit 0
}

Write-Host "FAIL: AutoTrading still disabled at API level"
exit 1
