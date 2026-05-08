#!/usr/bin/env bash
set -euo pipefail

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

echo -e "${YELLOW}=== EDDA setup ===${NC}"
echo

if command -v pdm &>/dev/null; then
    PDM="pdm"
else
    echo "  PDM not found. Installing..."
    pip install pdm || python3 -m pip install pdm || { echo -e "${RED}Failed to install PDM${NC}"; exit 1; }
    PDM="python3 -m pdm"
fi

echo "Installing dependencies..."
$PDM sync

echo
echo -e "${GREEN}Done. Run ./update.sh to import journals and build the dashboard.${NC}"
