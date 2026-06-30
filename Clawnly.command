#!/bin/bash
# Double-click this file to launch Clawnly.
# It starts the local server and opens the app in your browser.

cd "$(dirname "$0")"

if [ ! -x ".venv/bin/python" ]; then
  echo "First-time setup needed. Run these once in Terminal, then double-click again:"
  echo ""
  echo "  python3.14 -m venv .venv"
  echo "  .venv/bin/python -m pip install -r requirements.txt"
  echo ""
  read -p "Press Enter to close this window..."
  exit 1
fi

echo "Starting Clawnly... your browser will open in a moment."
echo "(Keep this window open while you use the app. Close it or press Ctrl+C to stop.)"
.venv/bin/python src/app.py
