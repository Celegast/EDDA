$ErrorActionPreference = "Stop"

function Step($n, $total, $label) {
    Write-Host ""
    Write-Host "[$n/$total] $label" -ForegroundColor Cyan
}

function Run {
    param([string[]]$cmd)
    $exe  = $cmd[0]
    $rest = if ($cmd.Length -gt 1) { $cmd[1..($cmd.Length - 1)] } else { @() }
    & $exe @rest
    if ($LASTEXITCODE -ne 0) { throw "Failed: $($cmd -join ' ')" }
}

Write-Host "=== EDDA update ===" -ForegroundColor Yellow

# 1. Pull latest code
Step 1 6 "Pulling latest changes..."
$hasGit = $null -ne (Get-Command git -ErrorAction SilentlyContinue)
if ($hasGit -and (Test-Path ".git")) {
    Run "git", "pull"
} elseif (-not $hasGit) {
    Write-Host "  git not found — skipping pull." -ForegroundColor DarkYellow
    Write-Host "  Download the latest release manually from the repository." -ForegroundColor DarkYellow
} else {
    Write-Host "  Not a git repository — skipping pull." -ForegroundColor DarkYellow
}

# 2. Create venv if absent
Step 2 6 "Virtual environment..."
if (-not (Test-Path ".venv")) {
    Write-Host "  Creating .venv..."
    Run "python", "-m", "venv", ".venv"
} else {
    Write-Host "  .venv already exists."
}

# 3. Install / sync dependencies
Step 3 6 "Installing current version into .venv..."
Run ".\.venv\Scripts\pip", "install", "-e", ".", "--quiet"

# 4. Import latest journal data
Step 4 6 "Importing journal data..."
Run ".\.venv\Scripts\edda-import"

# 5. Rebuild standalone outputs (maps + charts → output/)
Step 5 6 "Rebuilding maps and charts..."
Run ".\.venv\Scripts\edda-map"
Run ".\.venv\Scripts\edda-charts"

# 6. Rebuild dashboard
Step 6 6 "Rebuilding dashboard..."
Run ".\.venv\Scripts\edda-dashboard"

Write-Host ""
Write-Host "Done.  Open dashboard.html in a browser." -ForegroundColor Green
