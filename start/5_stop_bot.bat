@echo off
chcp 65001 >nul
set "TB_ROOT=%~dp0.."
cd /d "%TB_ROOT%"
call "%~dp0_load_env.bat"
title TradingBot - Stop
powershell -ExecutionPolicy Bypass -File "%TB_ROOT%\scripts\stop_live_daemon.ps1"
if errorlevel 1 (
  echo Stop script reported warnings.
  if /I not "%~1"=="--nopause" pause
  exit /b 1
)
echo Bot stopped.
if /I not "%~1"=="--nopause" pause
