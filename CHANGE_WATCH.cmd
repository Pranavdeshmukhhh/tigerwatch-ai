@echo off
setlocal
cd /d "%~dp0"
if not exist .venv\Scripts\python.exe goto :missing
.venv\Scripts\python.exe main.py --configure-watch watch.json
set "WatchExit=%errorlevel%"
pause
exit /b %WatchExit%
:missing
echo Run START_PUBLIC.cmd first.
pause
exit /b 1
