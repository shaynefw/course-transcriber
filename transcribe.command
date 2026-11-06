#!/bin/bash
# Double-click to transcribe everything new in ./videos, then rebuild INDEX.md + module bundles.
# Add --watch (or double-click transcribe-watch.command) to keep running and pick up new files.
cd "$(dirname "$0")" || exit 1

# The Python environment lives outside this folder (a "$" in the folder path breaks venv/pip).
VENV="$HOME/.transcriber/venv"
if [ ! -x "$VENV/bin/python" ]; then
  echo "First run: setting up the Python environment (one time, needs internet)..."
  python3 -m venv "$VENV" && "$VENV/bin/pip" install -q --upgrade pip && "$VENV/bin/pip" install -r requirements.txt \
    || { echo "Setup failed."; read -n 1 -s -r -p "Press any key to close"; exit 1; }
fi
# top up packages added in later versions (existing environments)
"$VENV/bin/python" -c "import PIL" 2>/dev/null || "$VENV/bin/pip" install -q -r requirements.txt

# caffeinate keeps the Mac awake while it works; extra args (--model medium, --watch...) pass through
caffeinate -i "$VENV/bin/python" transcribe.py "$@"

echo
read -n 1 -s -r -p "Finished. Press any key to close"
