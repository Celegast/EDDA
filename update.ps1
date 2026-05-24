$ErrorActionPreference = "Stop"

function Step($n, $total, $label) {
    Write-Host ""
    Write-Host "[$n/$total] $label" -ForegroundColor Cyan
}

Write-Host "=== EDDA update ===" -ForegroundColor Yellow

# 1. Pull latest code
Step 1 5 "Pulling latest changes..."
$hasGit = $null -ne (Get-Command git -ErrorAction SilentlyContinue)
if ($hasGit -and (Test-Path ".git")) {
    git pull
    if ($LASTEXITCODE -ne 0) { throw "git pull failed" }
} elseif (-not $hasGit) {
    Write-Host "  git not found — skipping pull." -ForegroundColor DarkYellow
    Write-Host "  Download the latest release manually from the repository." -ForegroundColor DarkYellow
} else {
    Write-Host "  Not a git repository — skipping pull." -ForegroundColor DarkYellow
}

# 2. Install dependencies
Step 2 5 "Installing dependencies..."
$usePythonMPdm = $false
if (Get-Command pdm -ErrorAction SilentlyContinue) {
    # pdm is in PATH, nothing to do
} else {
    python -m pdm --version 2>&1 | Out-Null
    if ($LASTEXITCODE -eq 0) {
        $usePythonMPdm = $true
    } else {
        Write-Host "Error: PDM not found." -ForegroundColor Red
        Write-Host "Install it with:  pip install pdm"
        Write-Host "Then ensure the Python Scripts directory is in your PATH."
        Write-Host "Typical location: $env:APPDATA\Python\PythonXXX\Scripts"
        exit 1
    }
}

function Pdm([string[]]$a) {
    if ($usePythonMPdm) { & python -m pdm @a } else { & pdm @a }
    if ($LASTEXITCODE -ne 0) { throw "pdm $($a -join ' ') failed" }
}

Pdm "install"

# 3. Import latest journal data
Step 3 5 "Importing journal data..."
Pdm "run", "import"

# 4. Rebuild maps and charts
Step 4 5 "Rebuilding maps and charts..."
Pdm "run", "map"
Pdm "run", "charts"

# 5. Rebuild dashboard
Step 5 5 "Rebuilding dashboard..."
Pdm "run", "dashboard"

Write-Host ""
Write-Host "Done.  Open dashboard.html in a browser." -ForegroundColor Green
