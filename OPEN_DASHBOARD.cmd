@echo off
setlocal
cd /d "%~dp0"
if not exist .venv\Scripts\python.exe goto :missing
.venv\Scripts\python.exe main.py --dashboard
set "DashboardExit=%errorlevel%"
pause
exit /b %DashboardExit%
:missing
echo Run START_PUBLIC.cmd first, then open this launcher again.
pause
exit /b 1
