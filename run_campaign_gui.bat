@echo off
cd /d "%~dp0"
set PYTHONPATH=%~dp0src
echo Starting Spider Solver campaign GUI (AUTO hardware)...
start "Spider Campaign" pythonw tools\campaign_gui.py
if errorlevel 1 (
  echo pythonw failed, trying python ...
  python tools\campaign_gui.py
  pause
)
