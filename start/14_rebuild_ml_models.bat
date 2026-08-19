@echo off
chcp 65001 >nul
cd /d "%~dp0.."
call "%~dp0_load_env.bat"
title TradingBot - Rebuild ML Models
echo.
echo === Rebuild Trend v41 + Range phase9_9 + verify ===
echo MT5 must be open for data collection if datasets are missing.
echo.
python scripts\verify_ml_live_ready.py
echo.
echo Step 1: ML data collection (skip if already done)...
python scripts\collect_ml_data.py
if errorlevel 1 (
  echo Data collection failed - check MT5 connection.
  pause
  exit /b 1
)
echo.
echo Step 2: Trend RF v41 bundle promotion...
python scripts\run_phase17d_bundle_promotion.py
if errorlevel 1 (
  echo Trend bundle promotion failed.
  pause
  exit /b 1
)
echo.
echo Step 3: Meta-labeler update...
python scripts\train_meta_labeler.py --update
echo.
echo Step 4: Final verify...
python scripts\verify_ml_live_ready.py
echo.
pause
