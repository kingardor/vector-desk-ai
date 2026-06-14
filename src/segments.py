"""
Segment parser and sequential executor for interleaved text + actions.

Brain output format:
    [emotion] some speech. [motion 2] more speech. [emotion] etc.

Segments are parsed in left-to-right order and executed sequentially —
each BLOCKS until complete — giving perfectly synchronized output.
"""

import re
import threading
from dataclasses import dataclass, asdict
from typing import Callable, TYPE_CHECKING

if TYPE_CHECKING:
    from src.vectorbot import VectorBot

from src.expressions import (
    resolve_emotion,
    resolve_motion,
    get_eye,
    get_trigger,
    get_ui_meta,
    VECTOR_DEFAULT_EYE as _DEFAULT_EYE,
)

# Captures everything inside [...] brackets
_BRACKET_RE = re.compile(r"\[([^\]]+)\]")

_LOOK_TOKENS = frozenset({"look", "see", "scan", "vision", "camera", "watch"})

# Display labels for motion directions
_MOTION_LABELS: dict[str, str] = {
    "forward":  "⬆ Forward",
    "back":     "⬇ Back",
    "left":     "↩ Turn Left",
    "right":    "↪ Turn Right",
    "stop":     "⏹ Stop",
    "lookup":   "↑ Head Up",
    "lookdown": "↓ Head Down",
    "liftup":   "↑ Lift Up",
    "liftdown": "↓ Lift Down",
}


@dataclass
class Segment:
    kind: str    # "speech" | "emote" | "motion" | "look"
    value: str   # spoken text | emotion name | motion direction
    label: str   # human-readable label for the UI timeline
    params: dict # {"duration": float} for motion; {"css_state": str, "chip_color": str} for emote


def parse_segments(text: str) -> list[Segment]:
    """
    Split brain output into an ordered list of Segments.
    Text between brackets → speech segments.
    Bracket contents → emote / motion / look segments.
    """
    segments: list[Segment] = []
    parts = _BRACKET_RE.split(text)

    for i, part in enumerate(parts):
        if i % 2 == 0:
            # Text between brackets
            speech = part.strip()
            # Remove any stray markdown artefacts like *action narration*
            speech = re.sub(r"\*[^*]+\*", "", speech).strip()
            if speech:
                segments.append(Segment(
                    kind="speech",
                    value=speech,
                    label=speech[:70] + ("…" if len(speech) > 70 else ""),
                    params={},
                ))
        else:
            # Bracket token
            seg = _parse_action_token(part.strip())
            if seg:
                segments.append(seg)

    # If nothing parsed (pure plain text, no brackets), treat whole text as speech
    if not segments and text.strip():
        clean = re.sub(r"\*[^*]+\*", "", text).strip()
        if clean:
            segments.append(Segment(kind="speech", value=clean, label=clean[:70], params={}))

    return segments


def _parse_action_token(token: str) -> Segment | None:
    """Classify and return a Segment for a single bracket token, or None."""
    lower = token.lower().strip()

    # ── look / vision ──────────────────────────────────────────────────────
    if lower in _LOOK_TOKENS:
        return Segment(kind="look", value="look", label="👀 Looking", params={})

    # ── motion (check before emotion — "stop" is also an emotion synonym) ──
    motion = resolve_motion(token)
    if motion:
        direction, duration = motion
        label = _MOTION_LABELS.get(direction, f"🚗 {direction.title()}")
        if duration != 1.0:
            label += f" {duration}s"
        return Segment(
            kind="motion",
            value=direction,
            label=label,
            params={"duration": duration},
        )

    # ── emotion ────────────────────────────────────────────────────────────
    emotion = resolve_emotion(token)
    if emotion:
        display, css_state, chip_color = get_ui_meta(emotion)
        return Segment(
            kind="emote",
            value=emotion,
            label=display,
            params={"css_state": css_state, "chip_color": chip_color},
        )

    print(f"[Segments] Unrecognised token: [{token}] — skipping")
    return None


class Executor:
    """
    Executes segments in left-to-right order.

    Pairing rule: when an [action] segment is immediately followed by a [speech]
    segment, they run CONCURRENTLY — the animation/motion fires in a background
    thread while say_blocking() runs on this thread. Both finish before the next
    segment starts. This gives the natural feel of Vector expressing an emotion
    *while* speaking rather than expressing it and then speaking.

    Standalone actions (not followed by speech) and standalone speech segments
    run sequentially as before.
    """

    def __init__(self, bot: "VectorBot"):
        self._bot = bot

    def run(
        self,
        segments: list[Segment],
        emit: Callable[[dict], None],
    ) -> None:
        i = 0
        while i < len(segments):
            seg = segments[i]
            nxt = segments[i + 1] if i + 1 < len(segments) else None

            if seg.kind in ("emote", "motion", "look") and nxt is not None and nxt.kind == "speech":
                # ── Paired concurrent execution ────────────────────────────
                emit({"type": "segment_start", **asdict(seg)})
                emit({"type": "segment_start", **asdict(nxt)})
                try:
                    self._run_paired(seg, nxt)
                except Exception as e:
                    print(f"[Executor] Paired error {seg.kind}+speech: {e}")
                emit({"type": "segment_done", **asdict(seg)})
                emit({"type": "segment_done", **asdict(nxt)})
                i += 2
            else:
                # ── Sequential execution ───────────────────────────────────
                emit({"type": "segment_start", **asdict(seg)})
                try:
                    self._execute(seg)
                except Exception as e:
                    print(f"[Executor] Error on {seg.kind}={seg.value!r}: {e}")
                emit({"type": "segment_done", **asdict(seg)})
                i += 1

    # ── Private ────────────────────────────────────────────────────────────────

    def _run_paired(self, action_seg: Segment, speech_seg: Segment) -> None:
        """
        Fire action and speech concurrently; speech drives the pacing.

        Animation triggers (emote/look) share the SDK behavior lock with say_text,
        so they can't be truly simultaneous at the gRPC level. We fire the animation
        in a background thread and immediately start speaking — the animation runs
        whenever the lock is free and we never wait on it. Motor commands (motion)
        use a separate motors API with no lock contention, so those are truly parallel.

        Eye colour is set instantly on this thread before speech starts, giving
        immediate visual feedback regardless of animation scheduling.
        """
        act = self._bot.action

        # 1. Eye colour — instant, no lock needed
        if action_seg.kind == "emote":
            act.eye_color(*get_eye(action_seg.value))
        elif action_seg.kind == "look":
            act.eye_color(*get_eye("look"))

        # 2. Fire action in background — do NOT wait for it
        def _run_action():
            try:
                if action_seg.kind == "emote":
                    act.trigger_blocking(
                        get_trigger(action_seg.value), ignore_body_track=True
                    )
                elif action_seg.kind == "motion":
                    self._drive(action_seg.value, action_seg.params.get("duration", 1.0))
                elif action_seg.kind == "look":
                    act.trigger_blocking(get_trigger("look"), ignore_body_track=True)
            except Exception as e:
                print(f"[Executor] Action thread error: {e}")

        threading.Thread(target=_run_action, daemon=True).start()

        # 3. Speak immediately — speech paces the segment, not the animation
        try:
            act.say_blocking(speech_seg.value)
        except Exception as e:
            print(f"[Executor] Speech error: {e}")

        # 4. Reset eye colour once speech ends (don't wait for animation)
        if action_seg.kind in ("emote", "look"):
            try:
                act.eye_color(*_DEFAULT_EYE)
            except Exception:
                pass

    def _execute(self, seg: Segment) -> None:
        """Sequential single-segment execution (for standalone actions / speech)."""
        act = self._bot.action

        if seg.kind == "speech":
            act.say_blocking(seg.value)

        elif seg.kind == "emote":
            act.eye_color(*get_eye(seg.value))
            act.trigger_blocking(get_trigger(seg.value), ignore_body_track=True)
            act.eye_color(*_DEFAULT_EYE)

        elif seg.kind == "motion":
            self._drive(seg.value, seg.params.get("duration", 1.0))

        elif seg.kind == "look":
            act.eye_color(*get_eye("look"))
            act.trigger_blocking(get_trigger("look"), ignore_body_track=True)
            act.eye_color(*_DEFAULT_EYE)

    _WHEEL = 150.0  # mm/s
    _HEAD  = 2.0
    _LIFT  = 2.0

    def _drive(self, direction: str, dur: float) -> None:
        act = self._bot.action
        if direction == "forward":
            act.drive_timed(self._WHEEL, self._WHEEL, dur)
        elif direction == "back":
            act.drive_timed(-self._WHEEL, -self._WHEEL, dur)
        elif direction == "left":
            act.drive_timed(-self._WHEEL, self._WHEEL, dur)
        elif direction == "right":
            act.drive_timed(self._WHEEL, -self._WHEEL, dur)
        elif direction == "stop":
            act.stop()
        elif direction == "lookup":
            act.head_timed(self._HEAD, dur)
        elif direction == "lookdown":
            act.head_timed(-self._HEAD, dur)
        elif direction == "liftup":
            act.lift_timed(self._LIFT, dur)
        elif direction == "liftdown":
            act.lift_timed(-self._LIFT, dur)

