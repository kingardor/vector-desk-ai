#!/usr/bin/env bash
# Launch Chrome pointing at the Vector web UI.
# - Kills any running Chrome instances first (Chrome is exclusively for Vector).
# - Polls until the web UI is reachable before opening.
# - Traps SIGTERM (from `tilt down`) to kill Chrome on exit.

set -e
URL="http://localhost:8000"

# ── Kill any existing Chrome ──────────────────────────────────────────────────
if pgrep -x "Google Chrome" > /dev/null 2>&1; then
    echo "[chrome] Killing existing Chrome instances..."
    pkill -a -i "Google Chrome" 2>/dev/null || true
    sleep 0.8
fi

# ── Wait for the web UI ───────────────────────────────────────────────────────
echo "[chrome] Waiting for $URL to be ready..."
ATTEMPT=0
MAX=90  # 3 minutes max
until curl -sf "$URL" > /dev/null 2>&1; do
    ATTEMPT=$((ATTEMPT + 1))
    if [ "$ATTEMPT" -ge "$MAX" ]; then
        echo "[chrome] Timed out waiting for $URL after ${MAX}s"
        exit 1
    fi
    sleep 2
done
echo "[chrome] Web UI is ready."

# ── Open Chrome in app mode (clean, no browser chrome) ───────────────────────
open -na "Google Chrome" --args \
    --new-window \
    --app="$URL" \
    --window-size=1440,900 \
    --window-position=100,50

echo "[chrome] Launched → $URL"

# ── Stay alive; kill Chrome when Tilt stops (SIGTERM) ────────────────────────
_shutdown() {
    echo "[chrome] tilt down detected — killing Chrome..."
    pkill -a -i "Google Chrome" 2>/dev/null || true
    exit 0
}
trap '_shutdown' TERM INT

# Keep the serve_cmd process alive so Tilt tracks it
tail -f /dev/null & wait
