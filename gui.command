#!/bin/bash
# Starts the Transcriber control panel and opens it in your browser (used by Transcriber.app).
cd "$(dirname "$0")" || exit 1
VENV="$HOME/.transcriber/venv"
if [ ! -x "$VENV/bin/python" ]; then
  osascript -e 'display notification "Setting up (one time, a few minutes)…" with title "Transcriber"'
  python3 -m venv "$VENV" && "$VENV/bin/pip" install -q --upgrade pip && "$VENV/bin/pip" install -r requirements.txt \
    || { osascript -e 'display notification "Setup failed. Open transcribe.command in Terminal to see why." with title "Transcriber"'; exit 1; }
fi
# top up packages added in later versions (existing environments)
"$VENV/bin/python" -c "import PIL" 2>/dev/null || "$VENV/bin/pip" install -q -r requirements.txt
mkdir -p "$HOME/.transcriber"
# The web-video downloader needs Python 3.10+ (Macs ship 3.9), so it gets its own small environment.
# First time only, in the background so the panel opens right away (see setup-downloader.command).
if [ ! -x "$HOME/.transcriber/venv-dl/bin/python" ]; then
  ( ./setup-downloader.command >> "$HOME/.transcriber/gui.log" 2>&1 & )
fi
exec "$VENV/bin/python" gui.py >> "$HOME/.transcriber/gui.log" 2>&1
