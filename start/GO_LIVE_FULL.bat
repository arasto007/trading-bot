@echo off
chcp 65001 >nul
set "TB_ROOT=%~dp0.."
cd /d "%TB_ROOT%"
call "%~dp0_load_env.bat"
title TradingBot - Full GO LIVE pipeline

echo ============================================
echo   FULL GO LIVE - automated pipeline
echo ============================================
echo.

echo [1] Stop any running bot...
powershell -NoProfile -ExecutionPolicy Bypass -File "%TB_ROOT%\scripts\stop_live_daemon.ps1" 2>nul
timeout /t 2 /nobreak >nul

echo [1b] Release MT5 IPC lock...
python "%TB_ROOT%\scripts\release_mt5_ipc_lock.py" 2>nul

echo [2] Fix MT5 Experts ini (allow algo trading)...
python "%TB_ROOT%\scripts\fix_mt5_experts_ini.py"

echo [3] Restart MT5 + enable Algo Trading (Ctrl+E)...
powershell -NoProfile -ExecutionPolicy Bypass -File "%TB_ROOT%\scripts\restart_mt5_and_enable_algo.ps1"
set "RESTART_RC=%ERRORLEVEL%"
if not "%RESTART_RC%"=="0" (
  echo.
  echo [FAIL] After restart AutoTrading still off.
  echo        Run: start\FIX_MT5_PYTHON_API.bat  (one-time manual fix in MT5 Options)
  echo        Or: Tools - Options - Expert Advisors - uncheck Python API block
  echo        Then Ctrl+E GREEN and re-run GO_LIVE_FULL.bat
  pause
  exit /b 1
)

echo [4] Execution check (order_check only — no real trade)...
python "%TB_ROOT%\scripts\smoke_test_execution.py"
if errorlevel 1 (
  echo [FAIL] Smoke test - see above
  pause
  exit /b 1
)

echo [5] Start LIVE watchdog...
powershell -NoProfile -ExecutionPolicy Bypass -File "%TB_ROOT%\scripts\start_live_daemon.ps1"
if errorlevel 1 (
  echo [FAIL] Daemon start failed
  pause
  exit /b 1
)

echo [6] Open dashboard...
start "" "%TB_ROOT%\RUN_DASHBOARD.bat"

echo.
echo ============================================
echo   SUCCESS - Bot LIVE + dashboard opening
echo   Keep MT5 open with Algo Trading GREEN
echo ============================================
timeout /t 8 /nobreak >nul
exit /b 0
