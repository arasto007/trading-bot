# Stop live kernel watchdog + bot — set manual_stop flag.
$ErrorActionPreference = "Continue"
$Root = Split-Path -Parent $PSScriptRoot
$dataDir = Join-Path $Root "data"
$Logs = Join-Path $Root "logs"
New-Item -ItemType Directory -Force -Path $dataDir | Out-Null
New-Item -ItemType Directory -Force -Path $Logs | Out-Null

$flag = Join-Path $dataDir "manual_stop.flag"
$line = "$(Get-Date -Format o)|stop_script"
$utf8NoBom = New-Object System.Text.UTF8Encoding $false
[System.IO.File]::WriteAllText($flag, $line + "`n", $utf8NoBom)
Write-Host "Manual stop flag set."

function Stop-ProcTree([int]$TargetPid) {
    if ($TargetPid -le 0) { return }
    try {
        & taskkill /F /T /PID $TargetPid 2>$null | Out-Null
    } catch {
        Stop-Process -Id $TargetPid -Force -ErrorAction SilentlyContinue
    }
}

$patterns = @(
    @{ Name = "python.exe"; Match = "run_live_watchdog" },
    @{ Name = "python.exe"; Match = "tradingbot.*--loop" }
)

$stopped = @()
foreach ($p in $patterns) {
    Get-CimInstance Win32_Process -Filter "Name='$($p.Name)'" -ErrorAction SilentlyContinue |
        Where-Object { $_.CommandLine -match $p.Match } |
        ForEach-Object {
            Write-Host "Stopping $($p.Name) PID $($_.ProcessId) [$($p.Match)]"
            Stop-ProcTree -TargetPid $_.ProcessId
            $stopped += $_.ProcessId
        }
}

Start-Sleep -Seconds 2

$remaining = @()
foreach ($p in $patterns) {
    Get-CimInstance Win32_Process -Filter "Name='$($p.Name)'" -ErrorAction SilentlyContinue |
        Where-Object { $_.CommandLine -match $p.Match } |
        ForEach-Object { $remaining += "$($p.Name):$($_.ProcessId)" }
}

$report = @{
    stopped_at = (Get-Date).ToUniversalTime().ToString("o")
    stopped_pids = $stopped
    remaining = $remaining
}
$reportPath = Join-Path $Logs "last_stop_report.json"
$report | ConvertTo-Json | Set-Content -Path $reportPath -Encoding UTF8

if ($remaining.Count -gt 0) {
    Write-Host "WARNING: Some bot processes may still be running:"
    $remaining | ForEach-Object { Write-Host "  $_" }
} else {
    Write-Host "All bot processes stopped."
}

Write-Host "Live kernel stopped."

Push-Location $Root
python scripts/release_mt5_ipc_lock.py 2>$null
Pop-Location
