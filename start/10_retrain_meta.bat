@echo off
cd /d "%~dp0.."
call "%~dp0_load_env.bat"
echo === Retrain Meta-Labeler (real features + OOS gate) ===
python scripts\train_meta_labeler.py
if errorlevel 1 exit /b 1
python scripts\show_meta_stats.py
pause
