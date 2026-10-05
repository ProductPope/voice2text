@echo off
chcp 65001 >nul
setlocal
cd /d "%~dp0.."
title dictAItor - nagrywanie probek
set PYTHONUTF8=1
if not exist ".venv\Scripts\dictaitor.exe" (
  echo Najpierw uruchom 1-instaluj.bat
  pause
  exit /b 1
)
echo.
echo  Nagrywasz probki do pomiaru jakosci. Zostaja tylko na tym komputerze
echo  (folder "nagrania"). Kazda probka: powiedz wiadomosc tak jak zwykle,
echo  razem z haslem na koncu, potem nacisnij Enter.
echo.
:next
set "NAME="
set /p NAME= Krotka nazwa probki (np. zakupy1, bez spacji): 
if not defined NAME goto :next
".venv\Scripts\dictaitor.exe" record nagrania "%NAME%"
echo.
choice /c TN /m " Nagrac kolejna probke"
if errorlevel 2 goto :end
goto :next
:end
echo.
echo  Gotowe. Uruchom 4-zmierz-jakosc.bat
pause
