@echo off
title KBM-to-XInput Virtual Controller
cd /d "%~dp0"

if exist ".venv\Scripts\python.exe" (
    start "" ".venv\Scripts\python.exe" app.py
) else (
    echo [ERROR] Python virtual environment not found in %~dp0.venv
    echo Please make sure Phase 1 setup was completed.
    pause
)
exit
