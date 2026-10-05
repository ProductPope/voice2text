@echo off
cd /d "%~dp0.."
if not exist "%APPDATA%\dictaitor\config.toml" ".venv\Scripts\dictaitor.exe" init
start "" notepad "%APPDATA%\dictaitor\config.toml"
