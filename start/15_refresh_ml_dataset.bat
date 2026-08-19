@echo off
chcp 65001 >nul
cd /d "%~dp0.."
call "%~dp0_load_env.bat"
title TradingBot - ML Dataset Refresh (Phase 22N)
echo.
echo === ML Dataset Refresh ===
echo Step 1: collect_ml_data.py --incremental
echo Step 2: build_ml_dataset.py --phase9-1
echo Step 3: verify timestamp / coverage / feature count
echo Requires MT5_LOGIN, MT5_PASSWORD, MT5_SERVER for incremental collection.
echo.
python scripts\scheduled_ml_refresh.py %*
set EXIT_CODE=%ERRORLEVEL%
if %EXIT_CODE% NEQ 0 (
  echo.
  echo ML dataset refresh failed with exit code %EXIT_CODE%.
  echo   1 = collect failed
  echo   2 = build failed
  echo   3 = verification failed
  pause
  exit /b %EXIT_CODE%
)
echo.
echo ML dataset refresh completed successfully.
echo Reports: tradingbot\ml\research\phase22n\
pause
exit /b 0
