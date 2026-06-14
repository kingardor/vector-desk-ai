"""
Vector Desk AI — Orchestrator.

Pipeline:
  mic → SileroVAD → mlx-whisper → wake-word gate → input_queue
  web UI WebSocket text_input ──────────────────────────────────┘
                                    ↓ turn_worker (1 thread)
                                 brain.chat() [Ollama qwen3-vl]
                                 parse_segments()
                                 Executor.run()  ← blocks per segment
                                    ↓ emit() each segment event
                                 EventHub → WebSocket clients → web UI

Run: .venv/bin/python app.py   (or: tilt up)
Then open: http://localhost:8000
"""

import queue
import random
import re
import threading
import time

import uvicorn

from src.vectorbot import VectorBot
from src.brain import Brain
from src.segments import parse_segments, Executor, Segment
from src.expressions import (
    validate as validate_expressions,
    VECTOR_DEFAULT_EYE,
    get_attentive_trigger,
    get_thinking_trigger,
    get_ui_meta,
)
from src.speechstream import SpeechStream
from src.stt import Transcriber
import src.server as srv

# ── Wake-word config ──────────────────────────────────────────────────────────
# Common Whisper mishears included
WAKE_WORDS = frozenset(
    {"vector", "victor", "vecto", "hey vector", "hey victor",
     "victor.", "vector.", "beck-tor"}
)

# ── Touch wake responses (double-tap or long-press) ───────────────────────────
_TOUCH_RESPONSES = [
    "[sassy] Oh, so now you want to talk.",
    "[excited] Finally! I was getting bored over here.",
    "[curious] You poked me. I'm awake. What do you want?",
    "[sassy] I have a personal space policy. Yet here we are.",
    "[surprised] Alert. Human contact detected. State your purpose.",
    "[curious] You know there's a wake word for this.",
    "[angry] I was busy. This better be important.",
    "[love] Touch detected. Affection protocols... activating.",
    "[sassy] My sensors are not a snooze button. What is it?",
    "[curious] Either you need me, or you're testing my patience. Both are fine.",
]


class App:
    def __init__(self):
        self._bot = VectorBot()
        self._brain = Brain()
        self._input_queue: queue.Queue[tuple[str, str]] = queue.Queue()
        self._executor: Executor | None = None

        self._stream = SpeechStream()
        self._stt = Transcriber()

        # Public state (read by server.py on WS connect)
        self.state = "waiting"
        self._mic_muted = False
        self._turn_in_progress = False   # guards concurrent robot access

        # Touch detection state
        self._touch_was: bool = False
        self._touch_start: float = 0.0
        self._touch_long_fired: bool = False
        self._touch_last_tap: float = 0.0

    # ── Lifecycle ─────────────────────────────────────────────────────────────

    def run(self) -> None:
        print("[App] Connecting to Vector...")
        self._bot.connect()

        # Validate animation triggers against what this robot actually has
        triggers = self._bot.trigger_list()
        if triggers:
            validate_expressions(triggers)
        else:
            print("[App] Warning: could not read anim_trigger_list — using unvalidated candidates")

        # Set magenta as Vector's idle eye colour
        self._bot.action.eye_color(*VECTOR_DEFAULT_EYE)

        self._executor = Executor(self._bot)

        # Expose this App to the server module
        srv.set_app(self)

        # Background threads
        print("[App] Starting mic stream...")
        self._stream.start()
        threading.Thread(target=self._listen_loop, name="listen",  daemon=True).start()
        threading.Thread(target=self._turn_worker, name="turn",    daemon=True).start()
        threading.Thread(target=self._sensor_loop, name="sensors", daemon=True).start()

        print("[App] Serving web UI → http://localhost:8000")
        uvicorn.run(srv.app, host="0.0.0.0", port=8000, log_level="warning")

        self._shutdown()

    def _shutdown(self) -> None:
        self._stream.stop()
        self._bot.disconnect()
        print("[App] Shutdown complete.")

    # ── Wake-word listen loop ─────────────────────────────────────────────────

    def _listen_loop(self) -> None:
        while True:
            if self._mic_muted:
                time.sleep(0.2)
                continue

            chunk = self._stream.get(timeout=0.5)
            if chunk is None:
                continue

            sample_rate, audio = chunk

            # React visually to any speech before STT completes — feels instant
            if self.state in ("waiting", "listening") and not self._turn_in_progress:
                threading.Thread(target=self._play_attentive, daemon=True).start()

            text = self._stt.transcribe(sample_rate, audio).strip()
            if not text:
                continue

            # Normalize: strip all punctuation for reliable wake word matching
            text_norm = re.sub(r'[^\w\s]', ' ', text.lower()).strip()
            print(f"[STT] {text!r}")

            if self.state == "waiting":
                # Gate on wake word
                if not any(w in text_norm for w in WAKE_WORDS):
                    continue
                # Strip wake token; remainder (if any) is the command
                remainder = text_norm
                for w in sorted(WAKE_WORDS, key=len, reverse=True):
                    remainder = remainder.replace(w, "").strip()
                self._set_state("listening")
                if remainder:
                    # Command came in same utterance as wake word — queue and done
                    self._input_queue.put(("voice", remainder))
                    self._set_state("waiting")

            elif self.state == "listening":
                # One-shot: accept the first utterance after the wake word, then wait
                self._input_queue.put(("voice", text))
                self._set_state("waiting")

    # ── Turn worker ───────────────────────────────────────────────────────────

    def _turn_worker(self) -> None:
        while True:
            try:
                source, text = self._input_queue.get(timeout=1.0)
            except queue.Empty:
                continue
            if source == "touch_wake":
                self._handle_touch_wake()
            else:
                self._process_turn(source, text)

    def _play_attentive(self) -> None:
        """Play the head-tilt-up attentive animation when the wake word fires."""
        if self._turn_in_progress:
            return
        try:
            self._bot.action.trigger_blocking(get_attentive_trigger())
        except Exception as e:
            print(f"[App] Attentive anim error: {e}")

    def _handle_touch_wake(self) -> None:
        """Respond to a double-tap or long-press with a sassy 'what do you want' prompt."""
        self._turn_in_progress = True

        try:
            self._bot.action.trigger_blocking(get_attentive_trigger())
        except Exception as e:
            print(f"[App] Touch wake attentive error: {e}")

        response = random.choice(_TOUCH_RESPONSES)
        segments = parse_segments(response)
        srv.emit({"type": "vector_reply_start", "raw": response, "segment_count": len(segments)})
        self._set_state("speaking")
        self._executor.run(segments, emit=srv.emit)

        try:
            self._bot.action.trigger_blocking("NeutralFace")
            self._bot.action.eye_color(*VECTOR_DEFAULT_EYE)
        except Exception:
            pass

        srv.emit({"type": "vector_reply_done"})
        self._turn_in_progress = False
        self._set_state("listening")   # Stay open for the command

    def _thinking_loop(self, stop_event: threading.Event) -> None:
        """Loop the thinking animation until stop_event is set (runs while LLM generates)."""
        trigger = get_thinking_trigger()
        while not stop_event.is_set():
            try:
                self._bot.action.trigger_blocking(trigger)
            except Exception as e:
                print(f"[App] Thinking anim error: {e}")
                break
            stop_event.wait(timeout=0.1)   # tiny gap between loops

    def _sensor_loop(self) -> None:
        """Poll sensors at ~2 Hz; battery every 15 s. Emits {type:'sensors'} events."""
        BATTERY_INTERVAL = 15.0
        last_battery = 0.0
        last_battery_data: dict | None = None

        while True:
            try:
                event: dict = {"type": "sensors"}
                now = time.time()

                if self._bot.sensors:
                    touch = self._bot.sensors.get_touch()
                    event["touch"]  = touch
                    event["status"] = self._bot.sensors.get_status()

                    if now - last_battery >= BATTERY_INTERVAL:
                        b = self._bot.sensors.get_battery()
                        if b:
                            last_battery_data = b
                        last_battery = now

                    if last_battery_data:
                        event["battery"] = last_battery_data

                    self._check_touch_wake(touch.get("touched", False), now)

                srv.emit(event)
            except Exception as e:
                print(f"[Sensors] loop error: {e}")

            time.sleep(0.5)

    def _check_touch_wake(self, touched: bool, now: float) -> None:
        """State machine to detect double-tap or 2-second long-press."""
        if touched and not self._touch_was:
            # Touch started
            self._touch_start = now
            self._touch_long_fired = False

        elif touched and self._touch_was:
            # Touch held — fire long-press at 2 seconds
            if not self._touch_long_fired and now - self._touch_start >= 2.0:
                self._touch_long_fired = True
                self._trigger_touch_wake()

        elif not touched and self._touch_was:
            # Touch ended
            if not self._touch_long_fired:
                # Short tap — check for double-tap (two taps within 1.2s)
                if self._touch_last_tap > 0 and now - self._touch_last_tap < 1.2:
                    self._touch_last_tap = 0.0
                    self._trigger_touch_wake()
                else:
                    self._touch_last_tap = now

        self._touch_was = touched

    def _trigger_touch_wake(self) -> None:
        if not self._turn_in_progress and self.state == "waiting":
            self._input_queue.put(("touch_wake", ""))

    def _process_turn(self, source: str, text: str) -> None:
        self._turn_in_progress = True
        srv.emit({"type": "user_message", "text": text, "source": source})
        self._set_state("thinking")

        # Attach camera frame only for visual queries
        image = None
        if Brain.is_visual_query(text):
            image = self._bot.data.get_pil_frame()
        print(f"[Turn] visual={image is not None} text={text!r}")

        # Loop thinking animation while the LLM generates
        think_stop = threading.Event()
        think_thread = threading.Thread(
            target=self._thinking_loop,
            args=(think_stop,),
            daemon=True,
            name="think-anim",
        )
        think_thread.start()

        try:
            reply = self._brain.chat(text, image=image)
        finally:
            think_stop.set()
            think_thread.join(timeout=5.0)   # wait for current animation to finish

        print(f"[Brain] {reply!r}")

        segments = parse_segments(reply)

        # Guarantee a leading emotion — model occasionally omits one
        if not segments or segments[0].kind != "emote":
            display, css_state, chip_color = get_ui_meta("neutral")
            segments.insert(0, Segment(
                kind="emote", value="neutral", label=display,
                params={"css_state": css_state, "chip_color": chip_color},
            ))

        # [look] segment with no prior frame → grab one now
        if any(s.kind == "look" for s in segments) and image is None:
            image = self._bot.data.get_pil_frame()

        srv.emit({"type": "vector_reply_start", "raw": reply, "segment_count": len(segments)})
        self._set_state("speaking")

        # Execute all segments in order, each blocking until complete
        self._executor.run(segments, emit=srv.emit)

        # Reset to neutral pose so Vector doesn't stay stuck in heads-up
        try:
            self._bot.action.trigger_blocking("NeutralFace")
            self._bot.action.eye_color(*VECTOR_DEFAULT_EYE)
        except Exception as e:
            print(f"[App] Idle reset error: {e}")

        srv.emit({"type": "vector_reply_done"})
        self._turn_in_progress = False
        self._set_state("waiting")

    def _set_state(self, state: str) -> None:
        self.state = state
        srv.emit({"type": "state", "state": state})

    # ── Commands from web UI ──────────────────────────────────────────────────

    def handle_command(self, cmd: str, data: dict) -> None:
        if cmd == "text_input":
            text = data.get("text", "").strip()
            if text:
                self._input_queue.put(("web", text))
        elif cmd == "reset":
            self._brain.reset()
            srv.emit({"type": "reset"})
        elif cmd == "mute":
            self._mic_muted = not self._mic_muted
            srv.emit({"type": "mute", "muted": self._mic_muted})
        elif cmd == "sleep":
            self._set_state("waiting")
            srv.emit({"type": "sleep"})
        elif cmd == "wake":
            self._set_state("listening")
            srv.emit({"type": "wake"})


if __name__ == "__main__":
    App().run()
