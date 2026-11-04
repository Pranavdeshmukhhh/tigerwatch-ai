param(
    [string]$PythonVersion = '3.11',
    [switch]$Dev,
    [switch]$PublicBrowser,
    [switch]$Configure
)
$ErrorActionPreference = 'Stop'
Set-Location (Split-Path $PSScriptRoot -Parent)
& py "-$PythonVersion" -m venv .venv
if ($LASTEXITCODE -ne 0) { throw 'Install Python from python.org with the py launcher, then try again.' }
$ProjectPython = Join-Path $PWD '.venv/Scripts/python.exe'
$RequirementsFile = if ($Dev) { 'requirements-dev.txt' } elseif ($PublicBrowser) { 'requirements-browser.txt' } else { 'requirements.txt' }
& $ProjectPython -m pip install -r $RequirementsFile
if ($LASTEXITCODE -ne 0) { throw 'Dependency installation failed. Check network access and Python version.' }
if ($PublicBrowser) {
    & $ProjectPython -m playwright install chromium
    if ($LASTEXITCODE -ne 0) { throw 'Browser installation failed. Check network access and available disk space.' }
}
if (-not (Test-Path '.env')) { Copy-Item '.env.example' '.env' }
& $ProjectPython main.py --demo
if ($LASTEXITCODE -ne 0) { throw 'Offline demo failed.' }
if ($Configure) {
    $SetupMode = if ($PublicBrowser) { '--setup-public' } else { '--setup' }
    & $ProjectPython main.py $SetupMode
    if ($LASTEXITCODE -ne 0) { throw 'Configuration did not complete. Review START_HERE.md.' }
}
Write-Host 'Setup complete. See START_HERE.md for your selected source and live verification.'
