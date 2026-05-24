$ErrorActionPreference = "Stop"

Write-Host "=== EDDA Query Builder ===" -ForegroundColor Yellow
Write-Host ""

if (-not (Test-Path ".venv")) {
    Write-Host "ERROR: Virtual environment not found." -ForegroundColor Red
    Write-Host "Please run setup.ps1 first to install dependencies."
    exit 1
}

pdm run serve $args
