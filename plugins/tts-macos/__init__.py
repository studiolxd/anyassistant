"""macOS voices through `say` (`say -v '?'` lists them)."""

import subprocess
import tempfile
import wave
from pathlib import Path

import numpy as np

from tts import RATE, Voice, register, say_voices


@register("macos")
class MacOS(Voice):
    def synthesize(self, text: str) -> np.ndarray:
        with tempfile.TemporaryDirectory() as folder:
            output = Path(folder) / "voice.wav"
            command = ["say", "-v", self.voice, "-o", str(output),
                       "--file-format=WAVE", f"--data-format=LEI16@{RATE}"]
            if self.rate:
                command += ["-r", str(self.rate)]  # words per minute
            subprocess.run(command + ["--", text], check=True)
            with wave.open(str(output)) as w:
                return np.frombuffer(w.readframes(w.getnframes()), dtype=np.int16)

    @classmethod
    def voices(cls, language: str) -> list[str]:
        return say_voices(language)
