@echo off
chcp 65001 >nul
cd /d "%~dp0"
title TradingBot Dashboard v10.0.0
set "PY=python"
if exist "%~dp0.venv\Scripts\python.exe" set "PY=%~dp0.venv\Scripts\python.exe"
"%PY%" "%~dp0scripts\dashboard_server.py"
if errorlevel 1 pause
