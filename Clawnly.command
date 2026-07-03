#!/bin/bash
# Double-click this file to launch Clawnly.
# It sets up (first time) or updates the environment as needed, starts the local
# server, and opens the app in your browser -- no terminal commands required.

cd "$(dirname "$0")"

# find a Python to bootstrap the environment with (only used the first time).
PYBOOT=""
for p in python3.14 python3.13 python3.12 python3.11 python3; do
  if command -v "$p" >/dev/null 2>&1; then PYBOOT="$p"; break; fi
done

# first run: create the virtual environment and install everything.
if [ ! -x ".venv/bin/python" ]; then
  if [ -z "$PYBOOT" ]; then
    echo "No Python found. Install Python 3.11+ from python.org, then double-click this again."
    read -p "Press Enter to close this window..."
    exit 1
  fi
  echo "First-time setup: building the environment (this takes a minute)..."
  "$PYBOOT" -m venv .venv
  .venv/bin/python -m pip install --quiet --upgrade pip
  .venv/bin/python -m pip install -r requirements.txt
fi

# keep dependencies current: if anything the app needs is missing (e.g. after a
# pull that added a package), install from requirements. Fast no-op otherwise.
if ! .venv/bin/python -c "import fastapi, uvicorn, anthropic" >/dev/null 2>&1; then
  echo "Updating dependencies..."
  .venv/bin/python -m pip install -r requirements.txt
fi

echo "Starting Clawnly... your browser will open in a moment."
echo "(Keep this window open while you use the app. Close it or press Ctrl+C to stop.)"
.venv/bin/python src/app.py
