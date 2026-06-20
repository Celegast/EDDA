#!/usr/bin/env bash
set -euo pipefail

if [ ! -d ".venv" ]; then
    echo "ERROR: Virtual environment not found."
    echo "Please run ./setup.sh first to install dependencies."
    exit 1
fi

nohup .venv/bin/python -c "from edda.gui import main; main()" >/dev/null 2>&1 &
disown
