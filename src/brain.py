"""
Local AI brain — Ollama + qwen3-vl:2b.
Single model handles both text chat and on-demand vision (camera frame injected as image).

History management:
    Keeps last KEEP_RECENT messages verbatim.
    When history exceeds MAX_HISTORY the oldest turns are summarised into a compact
    memory block and folded back in, so Vector retains long-term context without
    the prompt growing unbounded.
"""

import base64
import io
import pathlib
import re

from PIL import Image
import ollama

MODEL           = "qwen3.5:4b-q4_K_M"
SUPPORTS_VISION = False   # text-only model; set True for qwen3-vl / InternVL etc.
MAX_HISTORY  = 20   # total messages before compression triggers
KEEP_RECENT  = 8    # newest messages always kept verbatim

_PERSONA_PATH = pathlib.Path(__file__).parent.parent / "prompts" / "persona.txt"
_THINK_RE     = re.compile(r"<think>.*?</think>", re.DOTALL)

# Trigger camera frame injection only when user explicitly asks Vector to look
_VISUAL_KEYWORDS = frozenset({"look", "what do you see", "what can you see"})


class Brain:
    def __init__(self, model: str = MODEL):
        self.model    = model
        self._system  = _PERSONA_PATH.read_text().strip()
        self._history: list[dict] = []
        self._summary: str = ""   # running compressed summary of older turns

    # ── Public ────────────────────────────────────────────────────────────────

    def chat(self, user_text: str, image: Image.Image | None = None) -> str:
        """
        Send a user turn and return Vector's reply (with interleaved [action] tokens).
        Automatically compresses history when it grows too long.
        """
        msg: dict = {"role": "user", "content": user_text}
        if image is not None and SUPPORTS_VISION:
            msg["images"] = [self._encode_image(image)]

        self._history.append(msg)
        messages = [{"role": "system", "content": self._system}] + self._history

        response = ollama.chat(
            model=self.model,
            messages=messages,
            options={
                "temperature": 0.85,
                "num_predict": 400,
                "stop": ["\n\n"],
                "think": False,
            },
        )

        raw   = _THINK_RE.sub("", response["message"]["content"]).strip()
        # Enforce ONE LINE: take the first non-empty line (model may lead with \n)
        reply = next((l.strip() for l in raw.splitlines() if l.strip()), "")
        self._history.append({"role": "assistant", "content": reply})
        self._maybe_compress()
        return reply

    def reset(self) -> None:
        self._history.clear()
        self._summary = ""

    @staticmethod
    def is_visual_query(text: str) -> bool:
        """True only when the user explicitly asks Vector to look at something."""
        import re
        lower = text.lower()
        return bool(re.search(r'\blook\b', lower)) or any(kw in lower for kw in _VISUAL_KEYWORDS)

    # ── Private ───────────────────────────────────────────────────────────────

    def _maybe_compress(self) -> None:
        """
        When history exceeds MAX_HISTORY, summarise old turns into a compact memory
        block and replace them. The running _summary accumulates across compressions
        so no context is permanently lost.
        """
        if len(self._history) <= MAX_HISTORY:
            return

        recent  = self._history[-KEEP_RECENT:]
        old     = self._history[:-KEEP_RECENT]

        # Exclude image blobs from the summary (they're large and meaningless as text)
        turns_text = "\n".join(
            f"{m['role'].upper()}: {m['content']}"
            for m in old
            if "images" not in m
        )

        if self._summary:
            prompt = (
                f"Prior summary: {self._summary}\n\n"
                f"New exchanges to fold in:\n{turns_text}\n\n"
                "Update the summary. Under 80 words. Plain prose only. "
                "Capture key topics, facts, and emotional tone."
            )
        else:
            prompt = (
                f"Summarise this conversation in under 80 words. "
                f"Plain prose only. Key topics, facts, emotional tone:\n\n{turns_text}"
            )

        try:
            resp = ollama.chat(
                model=self.model,
                messages=[{"role": "user", "content": prompt}],
                options={"temperature": 0.2, "num_predict": 120},
            )
            self._summary = _THINK_RE.sub("", resp["message"]["content"]).strip()
            self._history = [
                {"role": "user",      "content": f"[Conversation so far: {self._summary}]"},
                {"role": "assistant", "content": "[Got it.]"},
                *recent,
            ]
            print(f"[Brain] History compressed ({len(old)} → summary). "
                  f"Keeping {len(recent)} recent msgs.")
        except Exception as e:
            print(f"[Brain] Compression failed, truncating to recent: {e}")
            self._history = recent

    @staticmethod
    def _encode_image(pil_img: Image.Image) -> str:
        """JPEG-encode a PIL image to base64 for Ollama's images field."""
        buf = io.BytesIO()
        pil_img.convert("RGB").save(buf, format="JPEG", quality=80)
        buf.seek(0)
        return base64.b64encode(buf.getvalue()).decode()
