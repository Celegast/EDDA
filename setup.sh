#!/usr/bin/env bash
set -euo pipefail

RED='\033[0;31m'
NC='\033[0m'

die() { echo -e "${RED}Error: $*${NC}" >&2; exit 1; }

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

"$PYTHON" -m venv .venv
.venv/bin/pip install -e .

echo
echo "Done. Activate the environment with:"
echo "  source .venv/bin/activate"
echo
echo "Or call commands directly:"
echo "  .venv/bin/edda-import"
