# Vector Desk AI

MacBook as Vector's brain — 100% local on Apple Silicon.
Voice → Silero VAD → mlx-whisper → Ollama (qwen3-vl:2b) → Vector TTS + animations + motors.
On-demand vision: camera frame injected into the same LLM call when asked.

---

## Prerequisites

| Tool | Install |
|---|---|
| [WirePod](https://github.com/kercre123/WirePod/releases) | Download `WirePod-v*.dmg`, drag to Applications, launch |
| [Ollama](https://ollama.com) | `brew install ollama` |
| [uv](https://docs.astral.sh/uv/) | `brew install uv` |
| [Tilt](https://tilt.dev) | `brew install tilt` |
| portaudio | `brew install portaudio` |
| ffmpeg | `brew install ffmpeg` |

Python 3.11 is managed automatically by `uv`.

---

## Setup

### 1. Activate Vector with WirePod

1. Launch **WirePod.app** — opens a web UI at `http://localhost:8080`
2. Follow the activation flow. You'll need Vector's **IP** and **serial number**
   - Double-tap Vector's back button, then raise and lower the lift — these appear on his face
3. Keep WirePod running in the background.

### 2. Configure the SDK

```bash
python3 -m anki_vector.configure
```

When prompted for the server IP, enter `127.0.0.1`. This writes `~/.anki_vector/sdk_config.ini`.

### 3. Pull the model

```bash
ollama pull qwen3-vl:2b-instruct
```

### 4. Install Python dependencies

```bash
uv venv --python 3.11
uv pip install -r requirements.txt
```

---

## Run

### One-command start

```bash
tilt up
```

Tilt handles everything:
- `deps` — installs/refreshes Python deps when `requirements.txt` changes
- `wirepod-check` — verifies WirePod is reachable on :443
- `ollama` — starts Ollama if not already running
- `vector-app` — launches the app natively (mic + VAD + LLM + web UI on :8000)
- `chrome` — opens the UI in Chrome once the app is healthy

To stop: `tilt down`

### Manual fallback (no Tilt)

```bash
# Terminal 1
ollama serve

# Terminal 2
.venv/bin/python app.py
```

### Smoke test

```bash
.venv/bin/python scripts/smoke_test.py
```

Vector should speak "I am alive", play an animation, and save a frame to `/tmp/vector_frame.jpg`.

---

## Interaction

### Wake word (voice)

Say **"Vector"** into your Mac's mic. Silero VAD detects speech onset and fires the heads-up animation immediately — before transcription completes — so Vector reacts without delay. If the transcript contains "vector", the command is processed. If not (ambient speech, other people talking), Vector returns to waiting.

You can include the command in the same breath: *"Vector, what time is it?"* — the remainder after the wake word is queued automatically.

### Touch wake (double-tap or long-press)

**Double-tap** Vector's back touch sensor, or **hold for 2 seconds**, and Vector responds with a random "what do you want" line, then waits for your follow-up. No need to say "Vector" first.

### Type

Use the chat box in the web UI and press Enter.

### Vision

Say or type anything containing "look", "see", or "watch" — Vector grabs a camera frame and describes what he sees.

### UI controls

**Wake** / **Sleep** / **Mic** (mute toggle) / **Reset** (clear conversation history)

---

## Project layout

```
app.py                  # entry point + orchestrator
src/
  vectorbot.py          # SDK connection, camera, motors, animations, TTS
  brain.py              # Ollama client (chat + vision, with history compression)
  speechstream.py       # Mac mic + Silero VAD
  stt.py                # mlx-whisper transcription (Metal-accelerated)
  segments.py           # interleaved [action] token parser + Executor
  expressions.py        # emotion + motion vocabulary, animation resolver
  server.py             # FastAPI: WebSocket hub, MJPEG camera feed, static files
prompts/
  persona.txt           # Vector's system prompt (Ultron-soul, sassy + sharp)
web/
  index.html            # UI shell
  style.css             # warm charcoal design system
  app.js                # WebSocket client + avatar state machine
scripts/
  smoke_test.py         # robot connectivity check
  list_triggers.py      # enumerate animation triggers available on the robot
  ollama_serve.sh       # Tilt: start/keep-alive Ollama
  chrome.sh             # Tilt: open Chrome when UI is ready
requirements.txt
Tiltfile
```

---

## Tuning

| Setting | File | Notes |
|---|---|---|
| Whisper model | `src/stt.py → MODEL_NAME` | `"small.en"` (default) — best balance on Apple Silicon |
| Silence timeout | `src/speechstream.py → SILENCE_SECS` | how long to wait after speech ends before transcribing |
| VAD sensitivity | `src/speechstream.py → VAD_THRESHOLD` | lower = triggers on quieter speech |
| LLM model | `src/brain.py → MODEL` | any Ollama vision model tag |
| Personality | `prompts/persona.txt` | edit freely |

---

## How it works

1. **Silero VAD** runs in a background thread on the Mac mic. When it detects an utterance it buffers the audio and signals completion after `SILENCE_SECS` of silence.
2. **Attentive animation** fires immediately when any speech arrives — Vector looks up before transcription starts.
3. **mlx-whisper** transcribes the clip on Metal. If "vector" is in the result, the command is queued.
4. **Brain** sends the text (+ optional camera frame) to Ollama and gets back a response with interleaved `[emotion]`, `[motor]`, and speech tokens.
5. **Executor** plays each segment: emotion animations and speech run concurrently (animation fires async, speech drives timing). After each response, Vector resets to neutral pose.
6. **Web UI** receives segment events over WebSocket and animates the avatar eyes + status chip in real time.
