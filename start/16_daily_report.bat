@echo off
chcp 65001 >nul
set "TB_ROOT=%~dp0.."
cd /d "%TB_ROOT%"
call "%~dp0_load_env.bat"
title TradingBot - Daily Report
python "%TB_ROOT%\scripts\live_daily_report.py" --telegram
pause
