@echo off
setlocal
set PYTHONPATH=%~dp0src
python "%~dp0tools\campaign_gui.py"
endlocal
