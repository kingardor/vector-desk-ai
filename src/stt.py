"""
STT using mlx-whisper (Metal-accelerated on Apple Silicon).
Falls back gracefully if mlx_whisper isn't installed.
"""

import io
import numpy as np
import scipy.io.wavfile as wav_io

try:
    import mlx_whisper
    _BACKEND = "mlx"
except ImportError:
    import whisper as _openai_whisper
    _BACKEND = "openai"

MODEL_NAME = "small.en"   # better accuracy for proper nouns like "vector"; still fast on Apple Silicon


class Transcriber:
    def __init__(self, model: str = MODEL_NAME):
        self._model_name = model
        if _BACKEND == "mlx":
            # mlx_whisper loads the model lazily on first call
            self._model = None
        else:
            print("[STT] mlx_whisper not found, falling back to openai-whisper")
            self._model = _openai_whisper.load_model(model)

    def transcribe(self, sample_rate: int, audio: np.ndarray) -> str:
        """
        Accepts a (sample_rate, int16 ndarray) audio clip and returns transcript text.
        """
        if _BACKEND == "mlx":
            return self._transcribe_mlx(sample_rate, audio)
        else:
            return self._transcribe_openai(sample_rate, audio)

    def _transcribe_mlx(self, sample_rate: int, audio: np.ndarray) -> str:
        # mlx_whisper expects a float32 array or a WAV file path.
        # We write to an in-memory WAV and pass the path via a temp file.
        import tempfile, os
        audio_f32 = audio.astype(np.float32) / 32768.0
        with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as f:
            wav_io.write(f.name, sample_rate, (audio_f32 * 32767).astype(np.int16))
            tmp_path = f.name
        try:
            result = mlx_whisper.transcribe(
                tmp_path,
                path_or_hf_repo=f"mlx-community/whisper-{self._model_name}-mlx",
            )
            return result.get("text", "").strip()
        finally:
            os.unlink(tmp_path)

    def _transcribe_openai(self, sample_rate: int, audio: np.ndarray) -> str:
        audio_f32 = audio.astype(np.float32) / 32768.0
        result = self._model.transcribe(audio_f32, language="en", fp16=False)
        return result.get("text", "").strip()
