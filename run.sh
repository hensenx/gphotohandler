#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
VENV_DIR="$HOME/gphotohandler-venv"

if [[ ! -d "$VENV_DIR" ]]; then
    echo "Error: virtual environment not found at $VENV_DIR." >&2
    echo "Run ./install.sh first." >&2
    exit 1
fi

exec "$VENV_DIR/bin/python" "$SCRIPT_DIR/main.py"
