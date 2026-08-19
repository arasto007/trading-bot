@echo off
chcp 65001 >nul
cd /d "%~dp0.."
call "%~dp0_load_env.bat"
title TradingBot — بک‌تست سفارشی
if not exist data\hta_backtest_request.json (
  echo فایل درخواست پیدا نشد: data\hta_backtest_request.json
  pause
  exit /b 1
)
echo === بک‌تست — بازهٔ انتخاب‌شده در پنل ===
python scripts\backtest_custom_range.py --from-json data\hta_backtest_request.json
echo.
pause
