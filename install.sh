#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
VENV_DIR="$HOME/gphotohandler-venv"

# ── Python version check ──────────────────────────────────────────────────────
if ! command -v python3 &>/dev/null; then
    echo "Error: python3 not found. Install Python 3.10 or later and try again." >&2
    exit 1
fi

PYTHON_VERSION="$(python3 -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}")')"
PYTHON_MAJOR="${PYTHON_VERSION%%.*}"
PYTHON_MINOR="${PYTHON_VERSION#*.}"

if (( PYTHON_MAJOR < 3 || (PYTHON_MAJOR == 3 && PYTHON_MINOR < 10) )); then
    echo "Error: Python 3.10+ is required (found $PYTHON_VERSION)." >&2
    exit 1
fi

echo "Using Python $PYTHON_VERSION"

# ── Virtual environment ───────────────────────────────────────────────────────
if [[ ! -d "$VENV_DIR" ]]; then
    echo "Creating virtual environment at $VENV_DIR ..."
    python3 -m venv "$VENV_DIR"
else
    echo "Virtual environment already exists at $VENV_DIR — skipping creation."
fi

# ── Dependencies ──────────────────────────────────────────────────────────────
echo "Installing Python dependencies ..."
"$VENV_DIR/bin/pip" install --quiet --upgrade pip
"$VENV_DIR/bin/pip" install -r "$SCRIPT_DIR/requirements.txt"

# ── Playwright browser ────────────────────────────────────────────────────────
echo "Installing Playwright Chromium ..."
"$VENV_DIR/bin/playwright" install chromium

# ── Done ──────────────────────────────────────────────────────────────────────
echo ""
echo "Setup complete. Run the app with:"
echo "  ./run.sh"
