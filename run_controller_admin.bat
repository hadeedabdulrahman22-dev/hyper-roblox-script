@echo off
title KBM-to-XInput Virtual Controller (Admin)
cd /d "%~dp0"

echo Requesting Administrator privileges...
powershell -NoProfile -Command "Start-Process '%~dp0run_controller.bat' -WorkingDirectory '%~dp0' -Verb RunAs"
exit
