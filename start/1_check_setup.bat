@echo off
chcp 65001 >nul
set "TB_ROOT=%~dp0.."
cd /d "%TB_ROOT%"
call "%~dp0_load_env.bat"
title TradingBot Check Setup
echo === MT5 connection and config check ===
python "%TB_ROOT%\scripts\check_live_setup.py"
echo.
pause
