#!/usr/bin/env bash
# Start Ollama if not already running; otherwise keep alive by tailing it.
# Used by Tilt as a long-running serve_cmd.
set -e

if curl -sf http://localhost:11434/ > /dev/null 2>&1; then
    echo "[ollama] Already running — keeping Tilt resource alive"
    # Tail Ollama's log if it exists, otherwise just hold
    LOG="${HOME}/.ollama/logs/server.log"
    if [ -f "$LOG" ]; then
        exec tail -F "$LOG"
    else
        exec tail -f /dev/null
    fi
else
    echo "[ollama] Starting ollama serve..."
    exec ollama serve
fi
