#!/usr/bin/env bash
set -euo pipefail

CYAN='\033[0;36m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
DARK_YELLOW='\033[0;33m'
RED='\033[0;31m'
NC='\033[0m'

step() { echo; echo -e "${CYAN}[$1/5] $2${NC}"; }
die()  { echo -e "${RED}Error: $*${NC}" >&2; exit 1; }

echo -e "${YELLOW}=== EDDA update ===${NC}"

# 1. Pull latest code
step 1 "Pulling latest changes..."
if command -v git &>/dev/null && [ -d .git ]; then
    git pull
elif ! command -v git &>/dev/null; then
    echo -e "${DARK_YELLOW}  git not found — skipping pull.${NC}"
    echo -e "${DARK_YELLOW}  Download the latest release manually from the repository.${NC}"
else
    echo -e "${DARK_YELLOW}  Not a git repository — skipping pull.${NC}"
fi

# 2. Sync dependencies
step 2 "Syncing dependencies..."
if command -v pdm &>/dev/null; then
    PDM="pdm"
elif python3 -m pdm --version &>/dev/null 2>&1; then
    PDM="python3 -m pdm"
else
    die "PDM not found. Install with: pip install pdm\n  Then ensure the Python bin directory is in your PATH (e.g. ~/.local/bin)"
fi
$PDM sync

# 3. Import latest journal data
step 3 "Importing journal data..."
$PDM run import

# 4. Rebuild maps and charts
step 4 "Rebuilding maps and charts..."
$PDM run map
$PDM run charts

# 5. Rebuild dashboard
step 5 "Rebuilding dashboard..."
$PDM run dashboard

echo
echo -e "${GREEN}Done.  Open dashboard.html in a browser.${NC}"
