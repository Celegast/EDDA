#!/usr/bin/env bash
set -euo pipefail

echo "=== EDDA Query Builder ==="
echo

pdm run serve "$@"
