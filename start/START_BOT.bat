@echo off
chcp 65001 >nul
set "TB_ROOT=%~dp0.."
cd /d "%TB_ROOT%"
call "%~dp0_load_env.bat"
title TradingBot - START BOT
python "%TB_ROOT%\scripts\start_bot.py"
set "RC=%ERRORLEVEL%"
if %RC% equ 0 (
  start "" "%TB_ROOT%\RUN_DASHBOARD.bat"
)
echo.
if %RC% neq 0 pause
exit /b %RC%
