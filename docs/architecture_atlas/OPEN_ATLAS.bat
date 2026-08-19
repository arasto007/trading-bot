@echo off
chcp 65001 >nul
cd /d "%~dp0"

if not exist "assets\atlas-bundle.js" (
  echo Building atlas data...
  python "%~dp0build_atlas.py"
)

if not exist "assets\atlas-bundle.js" (
  echo [FAIL] atlas-bundle.js not found. Run: python docs\architecture_atlas\build_atlas.py
  pause
  exit /b 1
)

start "" "%~dp0index.html"
