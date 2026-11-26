#!/bin/bash
# ==============================================================================
# Launch wrapper for Easibot
# ==============================================================================

cd "$(dirname "$0")/.."

if [ -d "venv" ]; then
    source venv/bin/activate
fi

mkdir -p temp_audio assets/fonts

exec python3 main.py "$@"
