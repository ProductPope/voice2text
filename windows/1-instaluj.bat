@echo off
chcp 65001 >nul
setlocal
cd /d "%~dp0.."
title dictAItor - instalacja
echo.
echo  === dictAItor: instalacja ===
echo.

set "PY="
where py >nul 2>nul && set "PY=py -3"
rem Prefer 3.12: every dependency ships ready-made Windows packages for it.
if defined PY py -3.12 --version >nul 2>nul && set "PY=py -3.12"
if not defined PY (
  where python >nul 2>nul && set "PY=python"
)
if not defined PY goto :nopython
%PY% -c "import sys; sys.exit(0 if sys.version_info >= (3, 11) else 1)" >nul 2>nul
if errorlevel 1 goto :nopython

if not exist ".venv\Scripts\python.exe" (
  echo  [1/4] Tworze osobne srodowisko dla programu...
  %PY% -m venv .venv || goto :fail
) else (
  echo  [1/4] Srodowisko juz istnieje.
)

echo  [2/4] Instaluje skladniki (kilka minut, jednorazowo)...
".venv\Scripts\python.exe" -m pip install --upgrade pip --quiet || goto :fail
".venv\Scripts\python.exe" -m pip install -e ".[listen]" --quiet || goto :fail

echo  [3/4] Tworze plik ustawien (jesli go nie ma)...
if not exist "%APPDATA%\dictaitor\config.toml" ".venv\Scripts\dictaitor.exe" init

echo  [4/4] Pobieram model mowy i sprawdzam mikrofon...
set PYTHONUTF8=1
set HF_HUB_DISABLE_SYMLINKS_WARNING=1
".venv\Scripts\dictaitor.exe" prepare || goto :fail

echo.
echo  Gotowe! Teraz uruchom 2-dyktuj.bat
echo.
pause
exit /b 0

:nopython
echo  Nie znalazlem Pythona 3.11 lub nowszego.
echo  Zainstaluj go ze strony https://www.python.org/downloads/
echo  WAZNE: na pierwszym ekranie instalatora zaznacz "Add python.exe to PATH".
echo  Potem uruchom ten plik jeszcze raz.
echo.
pause
exit /b 1

:fail
echo.
echo  Cos poszlo nie tak. Zrob zrzut ekranu tego okna i wyslij go dalej.
echo.
pause
exit /b 1
