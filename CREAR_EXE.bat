@echo off
cd /d "%~dp0"
title Crear EXE Telegram Video Manager
py -m pip install pyinstaller
if errorlevel 1 python -m pip install pyinstaller
py -m PyInstaller --noconfirm --clean --windowed --name TelegramVideoManager app.py
if errorlevel 1 python -m PyInstaller --noconfirm --clean --windowed --name TelegramVideoManager app.py
echo.
echo Revisa la carpeta dist\TelegramVideoManager\
pause
