@echo off
rem Builds a standalone Capsule.exe (no Python needed for end users) into dist\Capsule\
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" call Capsule.bat
".venv\Scripts\python.exe" -m pip install pyinstaller
".venv\Scripts\python.exe" -m PyInstaller --noconfirm --windowed --name Capsule --icon capsule\assets\capsule.ico ^
  --add-data "capsule\assets;capsule\assets" ^
  --collect-all cv2 --collect-all sounddevice --collect-all pygrabber --collect-all comtypes entry.py
echo.
echo Done. Zip the dist\Capsule folder and upload it to the website.
pause
