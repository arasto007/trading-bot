@echo off
chcp 65001 >nul
cd /d "%~dp0.."
call "%~dp0_load_env.bat"
title TradingBot - ML Data Collection (Phase 1)
echo.
echo === ML Data Pipeline ===
echo H4=Market Bias | M15=Context | M5=Entry | M1=Data only
echo Requires MT5_LOGIN, MT5_PASSWORD, MT5_SERVER environment variables.
echo.
python scripts\collect_ml_data.py %*
pause
