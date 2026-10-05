@echo off
chcp 65001 >nul
cd /d "%~dp0.."
title dictAItor - pomiar jakosci
set PYTHONUTF8=1
set HF_HUB_DISABLE_SYMLINKS_WARNING=1
echo.
echo  Mierze jakosc na Twoich nagraniach (moze potrwac kilka minut)...
echo.
".venv\Scripts\dictaitor.exe" eval nagrania > wynik-pomiaru.txt 2>&1
type wynik-pomiaru.txt
echo.
echo  Wynik zapisany w pliku wynik-pomiaru.txt (w folderze programu).
echo  Mozesz go otworzyc i wkleic do rozmowy.
echo.
pause
