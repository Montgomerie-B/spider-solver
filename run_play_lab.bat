@echo off
setlocal
cd /d "%~dp0"
python tools\play_lab.py %*
if errorlevel 1 pause
