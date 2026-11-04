@echo off
setlocal
cd /d "%~dp0"
if not exist .venv\Scripts\python.exe goto :missing
if not exist watch.json goto :missing
.venv\Scripts\python.exe main.py --watch watch.json
set "WatchExit=%errorlevel%"
pause
exit /b %WatchExit%
:missing
echo Run START_PUBLIC.cmd first, or configure watch.json using CHANGE_WATCH.cmd.
pause
exit /b 1
