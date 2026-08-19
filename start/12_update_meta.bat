@echo off
chcp 65001 >nul
cd /d "%~dp0.."
call "%~dp0_load_env.bat"
title TradingBot - Update Meta-Labeler
echo.
echo === Meta-Labeler update ===
echo MT5 must be open. First run does a full train.
echo.
python scripts\show_meta_stats.py
echo.
python scripts\train_meta_labeler.py --update
if errorlevel 1 (
  echo.
  echo Training failed - see details above.
  pause
  exit /b 1
)
echo.
python scripts\show_meta_stats.py
echo.
echo Done. If bot is LIVE, restart once to load new models.
pause
