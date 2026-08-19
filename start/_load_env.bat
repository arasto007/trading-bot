@echo off
REM Load project .env into current cmd session (called by start/*.bat)
set "ENV_FILE=%~dp0..\.env"
if not exist "%ENV_FILE%" exit /b 0
for /f "usebackq eol=# tokens=1,* delims==" %%A in ("%ENV_FILE%") do (
  if not "%%A"=="" set "%%A=%%B"
)
exit /b 0
