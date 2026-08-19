@echo off
chcp 65001 >nul
set "TB_ROOT=%~dp0.."
cd /d "%TB_ROOT%"
call "%~dp0_load_env.bat"
title TradingBot - Fix MT5 Python API
echo.
echo ============================================
echo   ONE-TIME MT5 FIX (Python API + Algo)
echo ============================================
echo.
echo MT5 must be OPEN on your screen.
echo This opens Options - Expert Advisors for you.
echo.
echo CHECK these two boxes manually:
echo   [x] Allow algorithmic trading
echo   [ ] Disable automatic trading via external Python API  ^(OFF!^)
echo.
echo Then OK, then Ctrl+E until Algo Trading is GREEN.
echo.
pause
powershell -NoProfile -ExecutionPolicy Bypass -Command "$p=Get-Process terminal64 -EA SilentlyContinue|Select -First 1;if(-not $p){Write-Host 'Open MT5 first'; exit 1}; $w=New-Object -ComObject WScript.Shell; $null=$w.AppActivate($p.Id); Start-Sleep -m 800; $w.SendKeys('^o'); Start-Sleep -m 1200; $w.SendKeys('%%e')"
echo.
echo After fixing in MT5, run: start\2_prepare_mt5_live.bat
pause
