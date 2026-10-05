@echo off
cd /d "%~dp0.."
if not exist ".venv\Scripts\pythonw.exe" (
  echo Najpierw uruchom 1-instaluj.bat
  pause
  exit /b 1
)
set PYTHONUTF8=1
set HF_HUB_DISABLE_SYMLINKS_WARNING=1
rem Starts without a console window; look for the dot icon in the tray.
start "" ".venv\Scripts\pythonw.exe" -m dictaitor.app
