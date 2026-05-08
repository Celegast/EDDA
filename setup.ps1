$ErrorActionPreference = "Stop"

Write-Host "=== EDDA setup ===" -ForegroundColor Yellow
Write-Host ""

$usePythonMPdm = $false
if (-not (Get-Command pdm -ErrorAction SilentlyContinue)) {
    Write-Host "  PDM not found. Installing..." -ForegroundColor DarkYellow
    pip install pdm
    if ($LASTEXITCODE -ne 0) { throw "Failed to install PDM" }
    $usePythonMPdm = $true
}

function Pdm([string[]]$a) {
    if ($usePythonMPdm) { & python -m pdm @a } else { & pdm @a }
    if ($LASTEXITCODE -ne 0) { throw "pdm $($a -join ' ') failed" }
}

Write-Host "Installing dependencies..."
Pdm "sync"

Write-Host ""
Write-Host "Done. Run update.ps1 to import journals and build the dashboard." -ForegroundColor Green
