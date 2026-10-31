"""Audio as 16-bit mono PCM at 48 kHz, in 20 ms chunks.

- to_mono: converts what arrives from the microphone (decoded Opus) to that format.
- Speaker: the outgoing track; plays whatever is queued, silence otherwise.
"""

import asyncio
import fractions
import time

import numpy as np
from aiortc import MediaStreamTrack
from av import AudioFrame

RATE = 48000
SAMPLES = 960  # 20 ms


def to_mono(frame) -> np.ndarray:
    data = frame.to_ndarray()
    channels = len(frame.layout.channels)
    if frame.format.is_planar:
        mono = data.mean(axis=0)
    else:
        mono = data.reshape(-1, channels).mean(axis=1)
    return mono.astype(np.int16)


class Speaker(MediaStreamTrack):
    kind = "audio"

    def __init__(self):
        super().__init__()
        self._queue = np.zeros(0, dtype=np.int16)
        self._start = None
        self._pts = 0
        self.last_sound = 0.0  # when the last non-silent sample went out

    @property
    def speaking(self) -> bool:
        return len(self._queue) > 0

    def play(self, pcm: np.ndarray):
        self._queue = np.concatenate([self._queue, pcm.astype(np.int16)])

    def stop(self):
        self._queue = np.zeros(0, dtype=np.int16)

    async def recv(self) -> AudioFrame:
        if self._start is None:
            self._start = time.time()
        wait = self._start + self._pts / RATE - time.time()
        if wait > 0:
            await asyncio.sleep(wait)

        chunk, self._queue = self._queue[:SAMPLES], self._queue[SAMPLES:]
        if len(chunk):
            self.last_sound = time.time()
        if len(chunk) < SAMPLES:
            chunk = np.pad(chunk, (0, SAMPLES - len(chunk)))

        frame = AudioFrame.from_ndarray(chunk.reshape(1, -1), format="s16", layout="mono")
        frame.sample_rate = RATE
        frame.pts = self._pts
        frame.time_base = fractions.Fraction(1, RATE)
        self._pts += SAMPLES
        return frame


def louder(pcm: np.ndarray, volume: float) -> np.ndarray:
    """Scaled by a volume from 0 to 1."""
    return (pcm.astype(np.float32) * volume).astype(np.int16)


def normalize(pcm: np.ndarray, peak: float = 0.95) -> np.ndarray:
    """Raises (or lowers) the volume until the peak reaches `peak` of full scale."""
    maximum = np.abs(pcm).max() if len(pcm) else 0
    if not maximum:
        return pcm
    return np.clip(pcm.astype(np.float32) * (peak * 32767 / maximum), -32768, 32767).astype(np.int16)
