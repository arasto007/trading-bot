@echo off
chcp 65001 >nul
set "TB_ROOT=%~dp0.."
cd /d "%TB_ROOT%"
call "%~dp0_load_env.bat"
title TradingBot - Status
python "%TB_ROOT%\scripts\status_live.py"
echo.
pause
