$ErrorActionPreference = "Stop"

if (-not (Test-Path ".venv")) {
    Write-Host "ERROR: Virtual environment not found." -ForegroundColor Red
    Write-Host "Please run setup.ps1 first to install dependencies."
    exit 1
}

Start-Process -FilePath ".venv\Scripts\pythonw.exe" `
    -ArgumentList @('-c', 'from edda.gui import main; main()')
