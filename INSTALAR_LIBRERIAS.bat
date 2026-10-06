@echo off
cd /d "%~dp0"
title Instalar Telegram Video Manager
py -m pip install --upgrade pip
py -m pip install -r requirements.txt
if errorlevel 1 (
  python -m pip install --upgrade pip
  python -m pip install -r requirements.txt
)
echo.
echo Librerias instaladas.
pause
