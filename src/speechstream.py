"""
Mac mic capture with Silero VAD endpointing.
Accumulates audio while voice is active, yields WAV chunks when the utterance ends.
"""

import io
import queue
import threading
import numpy as np
import sounddevice as sd
import scipy.io.wavfile as wav_io
import torch

SAMPLE_RATE  = 16000
BLOCK_SIZE   = 512          # ~32 ms per block at 16 kHz
VAD_THRESHOLD = 0.4         # Silero probability threshold
SILENCE_SECS  = 0.7         # seconds of silence to trigger end-of-utterance
MIN_SPEECH_SECS = 0.4       # ignore clips shorter than this


class SpeechStream:
    """
    Runs microphone capture + Silero VAD in a background thread.
    Call .get() (blocking) to receive the next utterance as (sample_rate, np.int16 array).
    """

    def __init__(self):
        self._model, self._vad_utils = torch.hub.load(
            repo_or_dir="snakers4/silero-vad",
            model="silero_vad",
            force_reload=False,
            onnx=False,
        )
        (self._get_speech_ts, *_) = self._vad_utils

        self._queue: queue.Queue = queue.Queue()
        self._running = False
        self._thread: threading.Thread | None = None

    # ── Public API ───────────────────────────────────────────────────────────

    def start(self):
        self._running = True
        self._thread = threading.Thread(target=self._capture_loop, daemon=True)
        self._thread.start()

    def stop(self):
        self._running = False

    def get(self, timeout: float | None = None) -> tuple[int, np.ndarray] | None:
        """Block until an utterance is available. Returns (sample_rate, int16 array)."""
        try:
            return self._queue.get(timeout=timeout)
        except queue.Empty:
            return None

    # ── Internal ─────────────────────────────────────────────────────────────

    def _capture_loop(self):
        buffer: list[np.ndarray] = []
        silence_blocks = 0
        speech_blocks = 0
        silence_limit = int(SILENCE_SECS * SAMPLE_RATE / BLOCK_SIZE)
        min_speech_blocks = int(MIN_SPEECH_SECS * SAMPLE_RATE / BLOCK_SIZE)

        def callback(indata, frames, time_info, status):
            nonlocal silence_blocks, speech_blocks
            chunk = indata[:, 0].copy()  # mono
            chunk_f32 = chunk.astype(np.float32)
            tensor = torch.from_numpy(chunk_f32)
            prob = self._model(tensor, SAMPLE_RATE).item()

            if prob > VAD_THRESHOLD:
                buffer.append(chunk_f32)
                speech_blocks += 1
                silence_blocks = 0
            else:
                if buffer:
                    silence_blocks += 1
                    buffer.append(chunk_f32)
                    if silence_blocks >= silence_limit:
                        if speech_blocks >= min_speech_blocks:
                            audio = np.concatenate(buffer)
                            audio_i16 = (audio * 32767).astype(np.int16)
                            self._queue.put((SAMPLE_RATE, audio_i16))
                        buffer.clear()
                        silence_blocks = 0
                        speech_blocks = 0

        with sd.InputStream(
            samplerate=SAMPLE_RATE,
            blocksize=BLOCK_SIZE,
            channels=1,
            dtype="float32",
            callback=callback,
        ):
            while self._running:
                sd.sleep(100)
