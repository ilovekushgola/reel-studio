@echo off
rem Reel Studio launcher
cd /d "%~dp0"
echo Starting Reel Studio...
python server.py %*
if errorlevel 1 (
  echo.
  echo Server exited with an error. Is Python on PATH?
  pause
)
