@echo off
chcp 65001 >nul
set "TB_ROOT=%~dp0.."
cd /d "%TB_ROOT%"
call "%~dp0_load_env.bat"
title TradingBot - Morning GO LIVE
echo.
echo ============================================
echo   MORNING CHECK + START LIVE
echo   1) Open MT5 and login FIRST
echo   2) Algo Trading must be GREEN (Ctrl+E)
echo ============================================
echo.
python "%TB_ROOT%\scripts\morning_go_live_check.py"
set "RC=%ERRORLEVEL%"
echo.
if %RC% neq 0 (
  echo Fix errors above, then run this again.
) else (
  echo Opening dashboard...
  start "" "%TB_ROOT%\RUN_DASHBOARD.bat"
)
pause
exit /b %RC%
