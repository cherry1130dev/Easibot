#!/bin/bash
# ==============================================================================
# Launch wrapper for Easibot with automatic GitHub update check on startup
# ==============================================================================

cd "$(dirname "$0")/.."

if [ -d "venv" ]; then
    source venv/bin/activate
fi

mkdir -p temp_audio assets/fonts

# Check GitHub for latest updates before starting (safe: ignores untracked .env)
if [ -d ".git" ] && command -v git &> /dev/null; then
    echo "[Easibot] Checking GitHub for latest updates..."
    if timeout 15s git fetch origin main 2>/dev/null; then
        LOCAL=$(git rev-parse HEAD 2>/dev/null)
        REMOTE=$(git rev-parse origin/main 2>/dev/null)
        if [ -n "$LOCAL" ] && [ -n "$REMOTE" ] && [ "$LOCAL" != "$REMOTE" ]; then
            echo "[Easibot] Update found ($LOCAL -> $REMOTE). Pulling..."
            CHANGED_REQS=$(git diff --name-only "$LOCAL" "$REMOTE" | grep -c "requirements.txt" || true)
            git reset --hard origin/main
            if [ "$CHANGED_REQS" -gt 0 ] && [ -f "requirements.txt" ]; then
                pip install -r requirements.txt || true
            fi
        else
            echo "[Easibot] Already on latest version."
        fi
    else
        echo "[Easibot] Offline or git fetch timed out. Starting existing code."
    fi
fi

TARGET_SCRIPT="${1:-main.py}"
shift 2>/dev/null || true

exec python3 "$TARGET_SCRIPT" "$@"
