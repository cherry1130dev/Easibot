#!/bin/bash
# ==============================================================================
# Launch wrapper for Easibot
# ==============================================================================

cd "$(dirname "$0")/.."

if [ -d "venv" ]; then
    source venv/bin/activate
fi

# Ensure output directory exists
mkdir -p temp_audio web/static/img assets/fonts

exec python3 main.py "$@"
