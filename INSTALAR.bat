@echo off
cd /d "%~dp0"
echo Instalando librerias...
"C:\Users\USUARIO DEL GOBIERNO\AppData\Local\Programs\Python\Python314\python.exe" -m pip install -r requirements.txt
echo.
echo Listo.
pause
