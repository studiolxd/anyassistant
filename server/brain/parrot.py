"""Phase 1: the parrot. Records what you say and plays it back when you stop.

While it repeats (and a little after) it doesn't listen, so it doesn't hear
itself: the same half-duplex the assistant uses when echo cancellation falls short.
"""

import time

import numpy as np

from audio import RATE

THRESHOLD = 600  # RMS from which it counts as speech
SILENCE = 0.8  # seconds of silence that end the sentence
MAXIMUM = 10  # maximum seconds recorded
GUARD = 0.7  # seconds without listening after repeating (latency + reverb)


class Parrot:
    def __init__(self, speaker, send):
        self.speaker = speaker
        self.send = send
        self.chunks = []
        self.silence = 0.0
        self.state = None
        self._state("listening")

    def _state(self, state: str):
        if state != self.state:
            self.state = state
            self.send({"type": "state", "state": state})

    def hear(self, pcm: np.ndarray):
        if self.speaker.speaking or time.time() - self.speaker.last_sound < GUARD:
            return
        if self.state == "repeating":
            self._state("listening")

        rms = float(np.sqrt(np.mean(pcm.astype(np.float32) ** 2)))

        if rms > THRESHOLD:
            self.silence = 0.0
            self._state("recording")
        if self.state != "recording":
            return

        self.chunks.append(pcm)
        if rms <= THRESHOLD:
            self.silence += len(pcm) / RATE
        duration = sum(len(c) for c in self.chunks) / RATE
        if self.silence >= SILENCE or duration >= MAXIMUM:
            self.speaker.play(np.concatenate(self.chunks))
            self.chunks = []
            self.silence = 0.0
            self._state("repeating")
