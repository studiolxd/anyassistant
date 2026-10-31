"""openWakeWord: small ONNX models running on the Mac's CPU.

--wake-word takes a built-in model (hey_jarvis, alexa, hey_mycroft…) or the path
to your own .onnx trained with openWakeWord.
"""

import logging
from pathlib import Path

import numpy as np

from wake import WakeWord, register

log = logging.getLogger("wake")

CHUNK = 1280  # 80 ms at 16 kHz, what the model expects


@register("openwakeword")
class OpenWakeWord(WakeWord):
    # Its audio history must always move forward, or after going to sleep it
    # would hear the old word again and wake up by itself.
    continuous = True

    def __init__(self, word=None, threshold=0.5):
        super().__init__(word or "hey_jarvis", threshold)
        import openwakeword
        from openwakeword.model import Model

        if Path(self.word).suffix == ".onnx":
            path = self.word
        elif self.word in openwakeword.models:
            path = openwakeword.models[self.word]["model_path"]
        else:
            raise ValueError(f"Unknown word: {self.word}. Available: {', '.join(openwakeword.models)}")
        self.phrase = Path(path).stem.split("_v")[0].replace("_", " ").capitalize()
        self.model = Model(wakeword_model_paths=[path])
        self.pending = np.zeros(0, dtype=np.int16)

    def listen(self, audio: np.ndarray) -> bool:
        pcm = (np.clip(audio, -1, 1) * 32767).astype(np.int16)
        self.pending = np.concatenate([self.pending, pcm])
        detected = False
        while len(self.pending) >= CHUNK:
            chunk, self.pending = self.pending[:CHUNK], self.pending[CHUNK:]
            score = max(self.model.predict(chunk).values())
            if score >= self.threshold:
                detected = True
            self._near_miss(score)
        return detected

    def _near_miss(self, score: float):
        """Logs the peak of each attempt: helps tune --threshold."""
        if score >= 0.05:
            self.peak = max(getattr(self, "peak", 0.0), score)
        elif getattr(self, "peak", 0.0):
            log.info("attempt: %.2f (threshold %.2f)", self.peak, self.threshold)
            self.peak = 0.0

    def reset(self):
        self.model.reset()
        self.pending = np.zeros(0, dtype=np.int16)
