"""
Text-to-speech using macOS `say` command → WAV temp file.
Produces 16000 Hz / 16-bit / mono audio, which is within the range
that Vector's audio.stream_wav_file() accepts (8000–16025 Hz).
"""

import pathlib
import subprocess
import tempfile
import wave


class TTSEngine:
    def __init__(self, voice: str = "Samantha", rate: int = 165):
        self.voice = voice
        self.rate  = rate  # words-per-minute

    def synth(self, text: str) -> str:
        """
        Synthesise text to a temporary WAV file.
        Returns the file path as a string. Caller is responsible for deletion.
        Raises on synthesis failure.
        """
        tmp = tempfile.NamedTemporaryFile(suffix=".wav", delete=False)
        tmp.close()
        path = tmp.name

        subprocess.run(
            [
                "say",
                "-v", self.voice,
                "-r", str(self.rate),
                "--file-format=WAVE",
                "--data-format=LEI16@16000",
                "-o", path,
                text,
            ],
            check=True,
            capture_output=True,
        )

        # Verify the output is in the range Vector accepts
        with wave.open(path, "rb") as wf:
            rate    = wf.getframerate()
            width   = wf.getsampwidth()
            chans   = wf.getnchannels()
            nframes = wf.getnframes()

        if not (8000 <= rate <= 16025) or width != 2 or chans != 1 or nframes == 0:
            raise ValueError(
                f"say produced incompatible WAV: {rate}Hz/{width*8}bit/{chans}ch "
                f"(Vector needs 8000–16025 Hz / 16-bit / mono)"
            )

        return path

    def available_voices(self) -> list[str]:
        """Return the list of voices installed on this Mac."""
        result = subprocess.run(["say", "-v", "?"], capture_output=True, text=True)
        return [line.split()[0] for line in result.stdout.strip().splitlines() if line]
