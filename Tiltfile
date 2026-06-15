# ── Vector Desk AI — Tiltfile ────────────────────────────────────────────────
#
# Usage:
#   tilt up    → installs deps, starts services, opens Chrome
#   tilt down  → stops everything, kills Chrome
#
# Prerequisites (must be running BEFORE tilt up):
#   1. WirePod.app — provides Vector's cloud server on :443
#
# Tilt manages:
#   • deps        — uv venv + pip install (rebuilds only when requirements.txt changes)
#   • vector-app  — native Python process (FastAPI, robot brain, mic, web UI on :8000)
#   • ollama      — local LLM server on :11434 (started if not already running)
#   • wirepod-check — verifies WirePod is up (fails fast if not)
#   • chrome      — opens the web UI in Chrome; kills it on `tilt down`

# ── Python virtualenv (uv) ────────────────────────────────────────────────────

local_resource(
    'deps',
    cmd='uv venv --python 3.11 && uv pip install -r requirements.txt',
    deps=['requirements.txt'],
    labels=['local'],
)

# ── Native app — mic + brain + web UI ────────────────────────────────────────

local_resource(
    'vector-app',
    serve_cmd='.venv/bin/python app.py',
    deps=['app.py', 'src/', 'prompts/', 'web/'],
    readiness_probe=probe(
        http_get=http_get_action(port=8000, path='/'),
        period_secs=3,
        failure_threshold=20,
    ),
    resource_deps=['deps', 'wirepod-check', 'ollama'],
    labels=['app'],
)

# ── WirePod check (must be launched manually as WirePod.app) ─────────────────

local_resource(
    'wirepod-check',
    cmd='nc -z localhost 443 && echo "✓ WirePod listening on :443" || (echo "✗ WirePod not running — open WirePod.app first" && exit 1)',
    labels=['local'],
    auto_init=True,
    trigger_mode=TRIGGER_MODE_MANUAL,
)

# ── Ollama (start if not already running) ─────────────────────────────────────

local_resource(
    'ollama',
    serve_cmd='bash scripts/ollama_serve.sh',
    readiness_probe=probe(
        http_get=http_get_action(port=11434, path='/'),
        period_secs=3,
        failure_threshold=15,
    ),
    labels=['local'],
)

# ── Chrome (opens when vector-app is healthy, killed on tilt down) ────────────

local_resource(
    'chrome',
    serve_cmd='bash scripts/chrome.sh',
    resource_deps=['vector-app'],
    labels=['browser'],
    trigger_mode=TRIGGER_MODE_AUTO,
)
