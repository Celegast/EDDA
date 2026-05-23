$ErrorActionPreference = "Stop"

Write-Host "=== EDDA Query Builder ===" -ForegroundColor Yellow
Write-Host ""

pdm run serve $args
