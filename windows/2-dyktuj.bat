@echo off
chcp 65001 >nul
cd /d "%~dp0.."
title dictAItor - dyktowanie
set PYTHONUTF8=1
set HF_HUB_DISABLE_SYMLINKS_WARNING=1
if not exist ".venv\Scripts\dictaitor.exe" (
  echo Najpierw uruchom 1-instaluj.bat
  pause
  exit /b 1
)
echo.
echo  Mow normalnie. Tekst NIE zostanie nigdzie wyslany, dopoki nie powiesz hasla.
echo  Po hasle tekst trafia do schowka - wklej go Ctrl+V tam, gdzie chcesz.
echo  Zamkniecie okna albo Ctrl+C konczy (bez wysylania).
echo.
".venv\Scripts\dictaitor.exe" listen
pause
