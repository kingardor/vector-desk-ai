"""
Local AI brain — Ollama.
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

MODEL           = "qwen3-vl:4b"
SUPPORTS_VISION = True    # VL model — set False for text-only models
MAX_HISTORY  = 20
KEEP_RECENT  = 8

_PERSONA_PATH = pathlib.Path(__file__).parent.parent / "prompts" / "persona.txt"

# Trigger camera frame injection only when user explicitly asks Vector to look
_VISUAL_KEYWORDS = frozenset({"look", "what do you see", "what can you see"})


def _extract_reply(raw: str) -> str:
    """
    Extract the actual response from a model output that may contain a
    <think>...</think> reasoning block.

    Strategy:
      1. If </think> is present, take everything after the LAST closing tag.
      2. If <think> appears without closing (token budget exceeded mid-think),
         strip from <think> onward — the model never finished its thought.
      3. Otherwise use the raw text as-is.
    Then take the first non-empty line (enforce ONE LINE rule).
    """
    think_end = raw.rfind("</think>")
    if think_end != -1:
        reply = raw[think_end + len("</think>"):].strip()
    elif "<think>" in raw:
        # Mid-think truncation — discard partial reasoning
        reply = raw[:raw.index("<think>")].strip()
    else:
        reply = raw.strip()

    return next((line.strip() for line in reply.splitlines() if line.strip()), "")


class Brain:
    def __init__(self, model: str = MODEL):
        self.model    = model
        self._system  = _PERSONA_PATH.read_text().strip()
        self._history: list[dict] = []
        self._summary: str = ""

    # ── Public ────────────────────────────────────────────────────────────────

    def chat(self, user_text: str, image: Image.Image | None = None) -> str:
        msg: dict = {"role": "user", "content": user_text}
        if image is not None and SUPPORTS_VISION:
            msg["images"] = [self._encode_image(image)]

        self._history.append(msg)
        messages = [{"role": "system", "content": self._system}] + self._history

        response = ollama.chat(
            model=self.model,
            messages=messages,
            think=False,          # top-level param, not inside options
            options={
                "temperature": 0.85,
                "num_predict": 400,
                "stop": ["\n\n"],
            },
        )

        raw   = response["message"]["content"]
        reply = _extract_reply(raw)
        self._history.append({"role": "assistant", "content": reply})
        self._maybe_compress()
        return reply

    def reset(self) -> None:
        self._history.clear()
        self._summary = ""

    @staticmethod
    def is_visual_query(text: str) -> bool:
        lower = text.lower()
        return bool(re.search(r'\blook\b', lower)) or any(kw in lower for kw in _VISUAL_KEYWORDS)

    # ── Private ───────────────────────────────────────────────────────────────

    def _maybe_compress(self) -> None:
        if len(self._history) <= MAX_HISTORY:
            return

        recent     = self._history[-KEEP_RECENT:]
        old        = self._history[:-KEEP_RECENT]
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
                think=False,
                options={"temperature": 0.2, "num_predict": 120},
            )
            self._summary = _extract_reply(resp["message"]["content"])
            self._history = [
                {"role": "user",      "content": f"[Conversation so far: {self._summary}]"},
                {"role": "assistant", "content": "[Got it.]"},
                *recent,
            ]
            print(f"[Brain] History compressed ({len(old)} msgs → summary).")
        except Exception as e:
            print(f"[Brain] Compression failed, truncating to recent: {e}")
            self._history = recent

    @staticmethod
    def _encode_image(pil_img: Image.Image) -> str:
        buf = io.BytesIO()
        pil_img.convert("RGB").save(buf, format="JPEG", quality=80)
        buf.seek(0)
        return base64.b64encode(buf.getvalue()).decode()
