#!/usr/bin/env bash
set -euo pipefail

echo "=== EDDA Query Builder ==="
echo

if [ ! -d ".venv" ]; then
    echo "ERROR: Virtual environment not found."
    echo "Please run ./setup.sh first to install dependencies."
    exit 1
fi

pdm run serve "$@"
