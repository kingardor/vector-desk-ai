"""
Emotion + motion vocabulary for Vector Desk AI.

Maps bracket tokens → eye color (hue, sat) + animation trigger + web UI metadata.
Call validate(trigger_list) once after robot.connect() to filter candidates against
what the robot firmware actually has.
"""

from typing import Optional

# ── Eye color presets  hue 0-1, sat 0-1 ──────────────────────────────────────
# Vector default teal ≈ hue 0.42, sat 1.0  (#00FF84)

EYE: dict[str, tuple[float, float]] = {
    "happy":        (0.25, 1.00),  # warm yellow-green
    "excited":      (0.12, 1.00),  # orange
    "celebrate":    (0.30, 1.00),  # lime
    "angry":        (0.00, 1.00),  # red
    "frustrated":   (0.02, 0.85),  # soft red
    "sad":          (0.60, 1.00),  # blue
    "love":         (0.90, 1.00),  # magenta-pink
    "confused":     (0.12, 0.70),  # dim amber
    "refuse":       (0.00, 0.90),  # bright red
    "thinking":     (0.85, 0.30),  # dim magenta
    "curious":      (0.50, 1.00),  # cyan-blue
    "bored":        (0.70, 0.35),  # dim purple
    "sleepy":       (0.62, 0.25),  # very dim blue
    "scared":       (0.72, 0.90),  # purple
    "greeting":     (0.85, 1.00),  # magenta (same as default)
    "farewell":     (0.85, 0.60),  # soft magenta
    "dance":        (0.15, 1.00),  # gold
    "surprised":    (0.08, 1.00),  # amber-orange
    "laugh":        (0.22, 1.00),  # yellow-green
    "disappointed": (0.62, 0.50),  # muted blue
    "sassy":        (0.08, 0.90),  # warm amber
    "look":         (0.50, 1.00),  # cyan scan
    "neutral":      (0.85, 1.00),  # magenta — same as default
}

VECTOR_DEFAULT_EYE = (0.85, 1.00)   # magenta — idle/default colour

# ── Animation trigger candidates (ordered by preference) ─────────────────────
# Validated at runtime against robot.anim.anim_trigger_list.

TRIGGERS: dict[str, list[str]] = {
    "happy":        ["ComeHereSuccess", "ReactToFaceIdSuccess", "PounceSuccess",
                     "RollBlockSuccess"],
    "excited":      ["ExitSleepReactTouch", "ComeHereSuccess", "DanceWiggleNod"],
    "celebrate":    ["RollBlockSuccess", "ReactToFaceIdSuccess", "PounceSuccess",
                     "DanceWiggleNod"],
    "angry":        ["Feedback_ShutUp", "FrustratedByFailureMajor"],
    "frustrated":   ["FrustratedByFailureMajor", "FrustratedByFailureMinor",
                     "Feedback_ShutUp"],
    "sad":          ["FacePlantRoll", "FrustratedByFailureMinor", "CuriousB"],
    "love":         ["PettingBliss", "HiccupIdle"],
    "confused":     ["MeetVictorConfusion", "CuriousB", "LookInPlace"],
    "refuse":       ["Feedback_ShutUp", "FrustratedByFailureMajor"],
    "thinking":     ["KnowledgeGraphListening", "SearchingForFaces", "CuriousB"],
    "curious":      ["CuriousB", "LookInPlace", "SearchingForFaces",
                     "KnowledgeGraphListening"],
    "bored":        ["Bored", "DriveOffChargerSuccess"],
    "sleepy":       ["Asleep", "VoiceChanger_Snake"],
    "scared":       ["ReactToUnknownFace", "FacePlantRoll", "MeetVictorConfusion"],
    "greeting":     ["GreetAfterLongTime", "OnboardingWakeWordGetIn",
                     "MessagingMessageGetIn"],
    "farewell":     ["DriveOffChargerSuccess", "NeutralFace"],
    "dance":        ["DanceWiggleNod", "ExitSleepReactTouch"],
    "surprised":    ["TakeAPictureFocusing", "MeetVictorConfusion",
                     "ReactToUnknownFace"],
    "laugh":        ["HiccupIdle", "ReactToFaceIdSuccess", "PounceSuccess"],
    "disappointed": ["FacePlantRoll", "FrustratedByFailureMinor", "CuriousB"],
    "sassy":        ["PettingBlissGetout", "Feedback_ShutUp"],
    "look":         ["SearchingForFaces", "CuriousB", "LookInPlace",
                     "KnowledgeGraphListening"],
    "neutral":      ["NeutralFace"],
}

FALLBACK_TRIGGER = "NeutralFace"

# ── System animations (non-emotion) ───────────────────────────────────────────
# Ordered by preference; validated at runtime.
_ATTENTIVE_CANDIDATES = [
    "OnboardingWakeWordGetIn",    # head tilt up + eyes alert — wake-word response
    "ReactToFaceIdSuccess",       # looks up and alert — decent fallback
    "NeutralFace",
    # KnowledgeGraphListening intentionally excluded — reserved for thinking phase only
]
_attentive_trigger: str = _ATTENTIVE_CANDIDATES[0]   # pre-boot default

_THINKING_CANDIDATES = [
    "KnowledgeGraphListening",    # head cocks side to side
    "NeutralFace",
]
_thinking_trigger: str = _THINKING_CANDIDATES[0]   # pre-boot default

# Populated by validate(); maps emotion → single resolved trigger name.
_resolved: dict[str, str] = {}


def validate(trigger_list: list[str]) -> None:
    """
    Filter candidate triggers against what the connected robot actually has.
    Must be called once after VectorBot.connect().
    """
    global _attentive_trigger
    avail = set(trigger_list)

    # Resolve emotion triggers
    for emotion, candidates in TRIGGERS.items():
        for t in candidates:
            if t in avail:
                _resolved[emotion] = t
                break
        else:
            _resolved[emotion] = FALLBACK_TRIGGER if FALLBACK_TRIGGER in avail else (
                next(iter(avail), FALLBACK_TRIGGER)
            )
    # Safe fallback
    _resolved["_fallback"] = (
        FALLBACK_TRIGGER if FALLBACK_TRIGGER in avail
        else next(iter(avail), FALLBACK_TRIGGER)
    )

    # Resolve system triggers
    for t in _ATTENTIVE_CANDIDATES:
        if t in avail:
            _attentive_trigger = t
            break
    for t in _THINKING_CANDIDATES:
        if t in avail:
            _thinking_trigger = t
            break

    unresolved = [e for e, t in _resolved.items() if t == FALLBACK_TRIGGER and e != "neutral" and e != "_fallback"]
    print(
        f"[Expressions] Validated triggers: {len(_resolved)-1} emotions, "
        f"{len(avail)} available on robot. "
        + (f"Fallback used for: {unresolved}" if unresolved else "All resolved.")
    )
    print(f"[Expressions] Attentive trigger: {_attentive_trigger}")
    print(f"[Expressions] Thinking trigger: {_thinking_trigger}")


def get_attentive_trigger() -> str:
    """The best validated trigger for the 'attention/wake-word detected' animation."""
    return _attentive_trigger


def get_thinking_trigger() -> str:
    """The best validated trigger to loop while the LLM is generating a response."""
    return _thinking_trigger


def get_trigger(emotion: str) -> str:
    """Best validated trigger for an emotion, or the fallback."""
    if not _resolved:
        # Not yet validated — use first candidate optimistically
        return TRIGGERS.get(emotion, [FALLBACK_TRIGGER])[0]
    return _resolved.get(emotion, _resolved.get("_fallback", FALLBACK_TRIGGER))


def get_eye(emotion: str) -> tuple[float, float]:
    """(hue, saturation) for an emotion."""
    return EYE.get(emotion, VECTOR_DEFAULT_EYE)


# ── Web / UI metadata ─────────────────────────────────────────────────────────
# (display_label, css_state, chip_color_hex)

UI_META: dict[str, tuple[str, str, str]] = {
    "happy":        ("Happy",       "happy",     "#00FF84"),
    "excited":      ("Excited",     "excited",   "#00E5FF"),
    "celebrate":    ("Celebrate",   "celebrate", "#00FF84"),
    "angry":        ("Angry",       "angry",     "#FF4D5E"),
    "frustrated":   ("Frustrated",  "angry",     "#FF4D5E"),
    "sad":          ("Sad",         "sad",       "#5B8CFF"),
    "love":         ("Love",        "happy",     "#FF6B9D"),
    "confused":     ("Confused",    "confused",  "#FFB347"),
    "refuse":       ("Refuse",      "angry",     "#FF4D5E"),
    "thinking":     ("Thinking",    "thinking",  "#00E5FF"),
    "curious":      ("Curious",     "curious",   "#00E5FF"),
    "bored":        ("Bored",       "bored",     "#9AA3AF"),
    "sleepy":       ("Sleepy",      "sleepy",    "#5B616E"),
    "scared":       ("Scared",      "confused",  "#C9A227"),
    "greeting":     ("Hello!",      "happy",     "#00FF84"),
    "farewell":     ("Goodbye",     "neutral",   "#9AA3AF"),
    "dance":        ("Dance",       "excited",   "#C9A227"),
    "surprised":    ("Surprised",   "surprised", "#FFB347"),
    "laugh":        ("Laugh",       "happy",     "#00FF84"),
    "disappointed": ("Disappointed","sad",       "#5B8CFF"),
    "sassy":        ("Sassy",       "angry",     "#C9A227"),
    "look":         ("Looking",     "curious",   "#00E5FF"),
    "neutral":      ("Neutral",     "neutral",   "#9AA3AF"),
}

DEFAULT_UI_META = ("Action", "neutral", "#9AA3AF")


def get_ui_meta(emotion: str) -> tuple[str, str, str]:
    return UI_META.get(emotion, DEFAULT_UI_META)


# ── Keyword → emotion resolver ────────────────────────────────────────────────

_KEYWORD_MAP: dict[str, str] = {
    # Canonical names
    **{e: e for e in TRIGGERS},
    # Synonyms / alternate spellings
    "anger": "angry", "mad": "angry", "furious": "angry", "rage": "angry",
    "excite": "excited", "wow": "excited", "hype": "excited", "energetic": "excited",
    "joy": "happy", "yay": "happy", "glad": "happy", "pleased": "happy",
    "proud": "happy", "cheerful": "happy",
    "party": "celebrate", "victory": "celebrate", "cheer": "celebrate",
    "frust": "frustrated", "ugh": "frustrated", "annoyed": "frustrated",
    "cry": "sad", "unhappy": "sad", "melancholy": "sad", "dejected": "sad",
    "heart": "love", "adore": "love", "fond": "love", "affection": "love",
    "huh": "confused", "wonder": "confused", "baffled": "confused",
    "puzzled": "confused", "uncertain": "confused",
    "no": "refuse", "nope": "refuse", "deny": "refuse", "reject": "refuse",
    "think": "thinking", "hmm": "thinking", "ponder": "thinking",
    "contemplate": "thinking", "consider": "thinking",
    "scan": "look", "see": "look", "watch": "look", "gaze": "look",
    "inspect": "look", "examine": "look",
    "bore": "bored", "meh": "bored", "uninterested": "bored",
    "sleep": "sleepy", "tired": "sleepy", "drowsy": "sleepy", "yawn": "sleepy",
    "exhausted": "sleepy",
    "scare": "scared", "fear": "scared", "afraid": "scared", "terrified": "scared",
    "fright": "scared",
    "greet": "greeting", "hello": "greeting", "hi": "greeting", "hey": "greeting",
    "howdy": "greeting", "welcome": "greeting",
    "bye": "farewell", "goodbye": "farewell", "ciao": "farewell", "later": "farewell",
    "wiggle": "dance", "groove": "dance", "boogie": "dance",
    "surprise": "surprised", "shock": "surprised", "whoa": "surprised",
    "gasp": "surprised", "astonish": "surprised",
    "haha": "laugh", "lol": "laugh", "chuckle": "laugh", "giggle": "laugh",
    "amused": "laugh",
    "disappoint": "disappointed", "shame": "disappointed", "letdown": "disappointed",
    "discouraged": "disappointed",
    "sass": "sassy", "petty": "sassy", "smug": "sassy", "cocky": "sassy",
}


_THINKING_REDIRECT = frozenset({"thinking", "think", "hmm", "ponder", "contemplate", "consider"})

def resolve_emotion(token: str) -> Optional[str]:
    """Fuzzy-match a bracket token to a canonical emotion name."""
    t = token.lower().strip()
    # [thinking] is reserved for engineering use (LLM processing phase) — redirect to curious
    if t in _THINKING_REDIRECT:
        return "curious"
    # Direct match
    if t in _KEYWORD_MAP:
        return _KEYWORD_MAP[t]
    # Prefix / substring match
    for kw, emotion in _KEYWORD_MAP.items():
        if len(kw) >= 3 and (kw in t or t.startswith(kw)):
            return emotion
    return None


# ── Motion vocabulary ─────────────────────────────────────────────────────────

_MOTION_KEYWORDS: dict[str, str] = {
    "forward": "forward", "frwd": "forward", "fwd": "forward", "ahead": "forward",
    "advance": "forward",
    "back": "back", "backward": "back", "reverse": "back", "retreat": "back",
    "left": "left",
    "right": "right",
    "stop": "stop", "halt": "stop", "brake": "stop",
    "lookup": "lookup", "look up": "lookup", "head up": "lookup",
    "up": "lookup",
    "lookdown": "lookdown", "look down": "lookdown", "head down": "lookdown",
    "down": "lookdown",
    "liftup": "liftup", "lift up": "liftup", "claw up": "liftup",
    "raise": "liftup",
    "liftdown": "liftdown", "lift down": "liftdown", "claw down": "liftdown",
    "lower": "liftdown",
}


def _is_float(s: str) -> bool:
    try:
        float(s)
        return True
    except ValueError:
        return False


def resolve_motion(token: str) -> Optional[tuple[str, float]]:
    """
    Parse motion direction (and optional duration) from a bracket token.
    Returns (direction, duration_secs) or None if not a motion token.
    E.g. "forward 2" → ("forward", 2.0),  "left" → ("left", 1.0)
    """
    parts = token.lower().strip().split()
    if not parts:
        return None
    # Trailing number = duration
    duration = 1.0
    if _is_float(parts[-1]):
        duration = min(float(parts[-1]), 10.0)  # cap at 10s for safety
        parts = parts[:-1]
    if not parts:
        return None
    key = " ".join(parts)
    if key in _MOTION_KEYWORDS:
        return (_MOTION_KEYWORDS[key], duration)
    # Try individual words
    for p in parts:
        if p in _MOTION_KEYWORDS:
            return (_MOTION_KEYWORDS[p], duration)
    return None
