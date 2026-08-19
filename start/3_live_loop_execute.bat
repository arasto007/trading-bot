@echo off
chcp 65001 >nul
set "TB_ROOT=%~dp0.."
cd /d "%TB_ROOT%"
call "%~dp0_load_env.bat"
call "%~dp0START_BOT.bat"
exit /b %ERRORLEVEL%
