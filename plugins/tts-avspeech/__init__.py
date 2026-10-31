"""macOS voices through AVSpeechSynthesizer, which stays loaded (~50 ms per sentence).

Same voices as `say`. If the enhanced version of a voice is downloaded (System
Settings → Accessibility → Spoken Content), it uses it.
Talks to avspeech_bridge.swift, built the first time into .build/.
"""

import base64
import json
import subprocess
import threading
from pathlib import Path

import numpy as np
from scipy.signal import resample_poly

import i18n
from swift import build
from tts import RATE, Voice, register


@register("avspeech")
class AVSpeech(Voice):
    def __init__(self, voice=None, rate=None):
        super().__init__(voice, rate)
        binary = build(Path(__file__).with_name("avspeech_bridge.swift"), "avspeech-bridge")
        self._process = subprocess.Popen(
            [str(binary)], stdin=subprocess.PIPE, stdout=subprocess.PIPE, text=True
        )
        self._turn = threading.Lock()  # synthesize() is called from threads

    def synthesize(self, text: str) -> np.ndarray:
        command = {"text": text, "voice": self.voice, "language": i18n.L("tts_language")}
        if self.rate:
            command["rate"] = self.rate
        with self._turn:
            self._process.stdin.write(json.dumps(command) + "\n")
            self._process.stdin.flush()
            answer = json.loads(self._process.stdout.readline())
        if "error" in answer:
            raise RuntimeError(answer["error"])
        audio = np.frombuffer(base64.b64decode(answer["audio"]), dtype=np.float32)
        sample_rate = round(answer["sample_rate"])
        if sample_rate != RATE:
            divisor = np.gcd(sample_rate, RATE)
            audio = resample_poly(audio, RATE // divisor, sample_rate // divisor)
        return (np.clip(audio, -1, 1) * 32767).astype(np.int16)

    def close(self):
        self._process.kill()
