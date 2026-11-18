@echo off
rem Capsule launcher: sets itself up on first run, then opens the settings window.
cd /d "%~dp0"
where py >nul 2>nul && (set PY=py -3) || (set PY=python)
if not exist ".venv\Scripts\python.exe" (
  echo First run: setting up Capsule, this takes a minute...
  %PY% -m venv .venv || (echo Python 3.10+ is required: https://www.python.org/downloads/ & pause & exit /b 1)
  ".venv\Scripts\python.exe" -m pip install --upgrade pip >nul
  ".venv\Scripts\python.exe" -m pip install -r requirements.txt || (pause & exit /b 1)
) else (
  ".venv\Scripts\python.exe" -m pip install -q --disable-pip-version-check -r requirements.txt >nul 2>nul
)
start "" ".venv\Scripts\pythonw.exe" -m capsule
