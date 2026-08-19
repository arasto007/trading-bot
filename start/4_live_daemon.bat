@echo off
chcp 65001 >nul
cd /d "%~dp0.."
call "%~dp0_load_env.bat"
title TradingBot — Daemon (alias)
call "%~dp03_live_loop_execute.bat"