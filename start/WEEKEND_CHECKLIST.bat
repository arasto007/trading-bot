@echo off
chcp 65001 >nul
set "TB_ROOT=%~dp0.."
cd /d "%TB_ROOT%"
call "%~dp0_load_env.bat"
title TradingBot - Weekend Readiness Checklist
echo ============================================
echo   Weekend Readiness Checklist
echo   Telegram: optional (not required)
echo ============================================
echo.
python "%TB_ROOT%\scripts\weekend_checklist.py"
set "RC=%ERRORLEVEL%"
echo.
if %RC% NEQ 0 (
  echo [FAILED] Fix issues above before Monday LIVE.
) else (
  echo [OK] Robot ready for Monday LIVE testing.
)
pause
exit /b %RC%
