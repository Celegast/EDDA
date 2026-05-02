#!/usr/bin/env bash
set -euo pipefail

CYAN='\033[0;36m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
DARK_YELLOW='\033[0;33m'
RED='\033[0;31m'
NC='\033[0m'

step() { echo; echo -e "${CYAN}[$1/6] $2${NC}"; }
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

# 2. Locate Python 3.12+
step 2 "Virtual environment..."
PYTHON=""
for py in python3.12 python3 python; do
    if command -v "$py" &>/dev/null; then
        if "$py" -c "import sys; sys.exit(0 if sys.version_info >= (3,12) else 1)" 2>/dev/null; then
            PYTHON="$py"
            break
        fi
    fi
done
[ -n "$PYTHON" ] || die "Python 3.12 or newer not found. Please install it first."

if [ ! -d .venv ]; then
    echo "  Creating .venv..."
    "$PYTHON" -m venv .venv
else
    echo "  .venv already exists."
fi

# 3. Install / sync dependencies
step 3 "Installing current version into .venv..."
.venv/bin/pip install -e . --quiet

# 4. Import latest journal data
step 4 "Importing journal data..."
.venv/bin/edda-import

# 5. Rebuild standalone outputs (maps + charts)
step 5 "Rebuilding maps and charts..."
.venv/bin/edda-map
.venv/bin/edda-charts

# 6. Rebuild dashboard
step 6 "Rebuilding dashboard..."
.venv/bin/edda-dashboard

echo
echo -e "${GREEN}Done.  Open dashboard.html in a browser.${NC}"
