@echo off
setlocal
title KBM-to-XInput Virtual Controller
cd /d "%~dp0"

rem --- find Python (prefer the "py" launcher) ---
set "PY="
where py >nul 2>nul
if not errorlevel 1 set "PY=py -3"
if not defined PY (
    where python >nul 2>nul
    if not errorlevel 1 set "PY=python"
)
if not defined PY goto :nopython

rem --- create the virtual environment if missing ---
if exist ".venv\Scripts\python.exe" goto :havevenv
echo Creating virtual environment - first run only...
%PY% -m venv .venv
if errorlevel 1 goto :fail

:havevenv
rem --- install packages if any are missing ---
".venv\Scripts\python.exe" -c "import vgamepad, pynput, customtkinter" >nul 2>nul
if not errorlevel 1 goto :run
echo Installing required packages - first run only...
".venv\Scripts\python.exe" -m pip install --upgrade pip
".venv\Scripts\python.exe" -m pip install -r requirements.txt
if errorlevel 1 goto :fail

:run
".venv\Scripts\python.exe" app.py
if errorlevel 1 goto :fail
exit /b 0

:nopython
echo.
echo [ERROR] Python was not found.
echo Install Python 3.10 or newer from https://www.python.org/downloads/
echo and tick "Add Python to PATH" during setup.
pause
exit /b 1

:fail
echo.
echo [ERROR] Something went wrong. Read the messages above.
pause
exit /b 1
