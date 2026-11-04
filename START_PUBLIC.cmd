@echo off
setlocal
cd /d "%~dp0"
py -3 -c "import sys; raise SystemExit(0 if sys.version_info >= (3,11) else 1)"
if errorlevel 1 goto :failed
py -3 -m venv .venv
if errorlevel 1 goto :failed
.venv\Scripts\python.exe -m pip install -r requirements-browser.txt
if errorlevel 1 goto :failed
.venv\Scripts\python.exe -m playwright install chromium
if errorlevel 1 goto :failed
.venv\Scripts\python.exe main.py --setup-public
if errorlevel 1 goto :failed
echo.
echo Setup complete. Double-click OPEN_DASHBOARD.cmd for private controls.
echo RUN_WATCH.cmd also runs your saved watch directly.
pause
exit /b 0
:failed
echo Setup could not finish. Check Python 3.11+, network access and README.md.
pause
exit /b 1
