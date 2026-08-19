@echo off
chcp 65001 >nul
set "TB_ROOT=%~dp0.."
cd /d "%TB_ROOT%"
call "%~dp0_load_env.bat"
title TradingBot - Demo Proof Status
python "%TB_ROOT%\scripts\demo_proof_status.py"
echo.
pause
