@echo off
chcp 65001 >nul
cd /d "%~dp0.."
call "%~dp0_load_env.bat"
title TradingBot — Dry Run (یک چرخه)
echo === تست بدون سفارش — یک چرخه ===
python -m tradingbot --live
echo.
pause
