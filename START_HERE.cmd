@echo off
setlocal
cd /d "%~dp0"
py -3.11 -m venv .venv
if errorlevel 1 goto :failed
.venv\Scripts\python.exe -m pip install -r requirements.txt
if errorlevel 1 goto :failed
.venv\Scripts\python.exe main.py --setup
if errorlevel 1 goto :failed
echo.
echo Setup saved locally. Follow START_HERE.md for the one-time Supabase and Meta steps.
pause
exit /b 0
:failed
echo.
echo Setup did not complete. Install Python 3.11 with its launcher, then read START_HERE.md.
pause
exit /b 1
