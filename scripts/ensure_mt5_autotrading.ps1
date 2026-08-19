# Enable Algo Trading on MT5 window (Ctrl+E) if API reports disabled.
$ErrorActionPreference = "SilentlyContinue"
$Root = Split-Path -Parent (Split-Path -Parent $PSScriptRoot)
if (-not (Test-Path $Root)) { $Root = "C:\Users\AMIR\Desktop\TradingBot new" }

Write-Host "=== Ensure MT5 Algo Trading ==="

$proc = Get-Process terminal64 -ErrorAction SilentlyContinue | Select-Object -First 1
if (-not $proc) {
    Write-Host "MT5 not running - open LiteFinance MT5 first"
    exit 1
}

Write-Host "MT5 PID $($proc.Id) path=$($proc.Path)"

# Run diagnose first
Push-Location $Root
$diag = & python scripts/diagnose_autotrading.py 2>&1 | Out-String
Write-Host $diag
if ($LASTEXITCODE -eq 0) {
    Write-Host "AutoTrading already OK"
    Pop-Location
    exit 0
}

if ($diag -notmatch "10027|tradeapi_disabled|trade_allowed=False") {
    Pop-Location
    exit 1
}

Write-Host "Sending Ctrl+E once on MT5 window..."
$wshell = New-Object -ComObject WScript.Shell
$null = $wshell.AppActivate([int]$proc.Id)
Start-Sleep -Milliseconds 800
$wshell.SendKeys("^e")
Start-Sleep -Milliseconds 1500

$diag2 = & python scripts/diagnose_autotrading.py 2>&1 | Out-String
Write-Host $diag2
Pop-Location
if ($LASTEXITCODE -eq 0) { exit 0 }
exit 1
