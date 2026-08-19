# راه‌اندازی ربات live به‌صورت daemon — با بستن ترمینال زنده می‌ماند.
$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot
$Logs = Join-Path $Root "logs"
New-Item -ItemType Directory -Force -Path $Logs | Out-Null

try {
    $manualStop = Join-Path $Root "data\manual_stop.flag"
    Remove-Item -Force $manualStop -ErrorAction SilentlyContinue

    Get-CimInstance Win32_Process -Filter "Name='python.exe'" -ErrorAction SilentlyContinue |
        Where-Object {
            $_.CommandLine -match 'run_live_watchdog' -or
            $_.CommandLine -match 'tradingbot.*--loop'
        } |
        ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }

    Start-Sleep -Seconds 2

    Push-Location $Root
    & python scripts/release_mt5_ipc_lock.py 2>$null | Out-Null
    Pop-Location

    # Phase 47B — PA-primary live: router + meta + ML shadow; weak engines off.
    if (-not $env:USE_ML_KERNEL) {
        $env:USE_ML_KERNEL = "false"
    }
    if (-not $env:ENABLE_ML_SHADOW) {
        $env:ENABLE_ML_SHADOW = "true"
    }
    if (-not $env:MULTI_ENGINE_ROUTER_ENABLED) {
        $env:MULTI_ENGINE_ROUTER_ENABLED = "true"
    }
    if (-not $env:ADAPTIVE_REGIME_ENABLED) {
        $env:ADAPTIVE_REGIME_ENABLED = "false"
    }
    if (-not $env:VOL_REGIME_ENABLED) {
        $env:VOL_REGIME_ENABLED = "false"
    }
    if (-not $env:META_LABEL_THRESHOLD) {
        $env:META_LABEL_THRESHOLD = "0.38"
    }
    $py = (Get-Command python).Source
    $script = Join-Path $Root "scripts\run_live_watchdog.py"
    $stamp = Get-Date -Format "yyyyMMdd_HHmmss"
    $out = Join-Path $Logs "watchdog_stdout_$stamp.log"
    $err = Join-Path $Logs "watchdog_stderr_$stamp.log"
    @"
watchdog_stdout=$out
watchdog_stderr=$err
started_at=$(Get-Date -Format o)
"@ | Set-Content -Path (Join-Path $Logs "watchdog_latest.logpaths.txt") -Encoding UTF8

    $proc = Start-Process -FilePath $py `
        -ArgumentList "`"$script`" --execute" `
        -WorkingDirectory $Root `
        -WindowStyle Hidden `
        -RedirectStandardOutput $out `
        -RedirectStandardError $err `
        -PassThru

    if (-not $proc -or -not $proc.Id) {
        Write-Host "ERROR: failed to spawn live watchdog process."
        exit 1
    }

    Start-Sleep -Seconds 2
    $alive = Get-Process -Id $proc.Id -ErrorAction SilentlyContinue
    if (-not $alive) {
        Write-Host "ERROR: watchdog exited immediately - see $err"
        if (Test-Path $err) {
            Get-Content $err -Tail 20 | ForEach-Object { Write-Host $_ }
        }
        exit 1
    }

    Write-Host "Live daemon started (watchdog PID $($proc.Id))."
    Write-Host "Logs: $Logs\watchdog.log"
    Write-Host "Stop: scripts\stop_live_daemon.ps1 or start\5_stop_bot.bat"
    exit 0
}
catch {
    Write-Host "ERROR: $($_.Exception.Message)"
    exit 1
}
