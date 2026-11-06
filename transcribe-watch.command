#!/bin/bash
# Double-click: transcribe everything in ./videos, then keep watching for new files. Ctrl-C to stop.
exec "$(dirname "$0")/transcribe.command" --watch
