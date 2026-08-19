@echo off
chcp 65001 >nul
set "TB_ROOT=%~dp0.."
cd /d "%TB_ROOT%"
call "%~dp0_load_env.bat"
title TradingBot - Prepare MT5 for LIVE
echo.
echo ============================================
echo   Step 1 before LIVE
echo   1) Open MT5 manually (LiteFinance demo)
echo   2) Press Ctrl+E - Algo Trading must be GREEN
echo   3) Then click LIVE on dashboard
echo ============================================
echo.
python "%TB_ROOT%\scripts\diagnose_autotrading.py" --attach-only
set "RC=%ERRORLEVEL%"
echo.
if %RC% EQU 0 (
  echo [OK] MT5 ready for LIVE - you can click LIVE on dashboard now.
) else (
  echo [FAIL] Fix MT5 first - dashboard will NOT auto-open MT5 anymore.
  echo        Enable Ctrl+E on: C:\Program Files\MetaTrader 5
)
echo.
pause
exit /b %RC%
