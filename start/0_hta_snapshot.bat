@echo off
chcp 65001 >nul
cd /d "%~dp0.."
call "%~dp0_load_env.bat"
set "PY=python"
if exist "%~dp0..\.venv\Scripts\python.exe" set "PY=%~dp0..\.venv\Scripts\python.exe"
"%PY%" scripts\status_snapshot.py
if errorlevel 1 (
  py -3 scripts\status_snapshot.py
)
