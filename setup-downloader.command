#!/bin/bash
# Sets up the downloader's own Python environment (~/.transcriber/venv-dl).
# Why: current yt-dlp needs Python 3.10+, but Macs ship Python 3.9. This uses a Python 3.10+ if you
# have one, otherwise downloads a small standalone Python 3.12 (about 30 MB, into ~/.transcriber/python)
# using the `uv` tool. Safe to re-run.
set -e
cd "$(dirname "$0")"
HOME_DIR="$HOME/.transcriber"
VENV_DL="$HOME_DIR/venv-dl"
MAIN="$HOME_DIR/venv/bin/python"
mkdir -p "$HOME_DIR"

if [ -x "$VENV_DL/bin/python" ] && "$VENV_DL/bin/python" -c "import sys; assert sys.version_info >= (3, 10); import yt_dlp, imageio_ffmpeg" 2>/dev/null; then
  echo "Downloader environment is already set up."
  exit 0
fi

PY=""
for c in python3.13 python3.12 python3.11 python3.10 /opt/homebrew/bin/python3 /usr/local/bin/python3; do
  if command -v "$c" >/dev/null 2>&1 && "$c" -c "import sys; sys.exit(0 if sys.version_info >= (3, 10) else 1)" 2>/dev/null; then PY="$(command -v "$c")"; break; fi
done

if [ -z "$PY" ]; then
  echo "No Python 3.10+ found. Getting a small standalone Python 3.12 with uv..."
  [ -x "$MAIN" ] || MAIN="python3"
  "$MAIN" -m pip install -q uv
  UV="$("$MAIN" -c 'import os, sys, sysconfig; print(os.path.join(sysconfig.get_path("scripts"), "uv"))')"
  export UV_PYTHON_INSTALL_DIR="$HOME_DIR/python"
  "$UV" python install 3.12
  PY="$("$UV" python find 3.12)"
fi

echo "Using $PY"
rm -rf "$VENV_DL"
"$PY" -m venv "$VENV_DL"
"$VENV_DL/bin/python" -m pip install -q --upgrade pip
"$VENV_DL/bin/python" -m pip install -q -r requirements-downloader.txt
echo "Downloader ready: $("$VENV_DL/bin/python" -c 'import yt_dlp; print("yt-dlp", yt_dlp.version.__version__)')"
