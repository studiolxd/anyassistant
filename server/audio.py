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


def beep(falling: bool = False) -> np.ndarray:
    """Two short notes: rising means «I'm listening»; falling, «going to sleep»."""
    notes = []
    for frequency in (1320, 880) if falling else (880, 1320):
        t = np.arange(int(0.09 * RATE)) / RATE
        envelope = np.minimum(1, np.minimum(t, t[::-1]) / 0.01)  # no clicks
        notes.append(np.sin(2 * np.pi * frequency * t) * envelope * 0.5 * 32767)
    return np.concatenate(notes).astype(np.int16)


def alarm_tone() -> np.ndarray:
    """An alarm: three quick high notes."""
    t = np.arange(int(0.12 * RATE)) / RATE
    envelope = np.minimum(1, np.minimum(t, t[::-1]) / 0.01)
    note = np.sin(2 * np.pi * 1760 * t) * envelope * 0.6 * 32767
    gap = np.zeros(int(0.08 * RATE))
    return np.concatenate([note, gap, note, gap, note]).astype(np.int16)


def louder(pcm: np.ndarray, volume: float) -> np.ndarray:
    """Scaled by a volume from 0 to 1."""
    return (pcm.astype(np.float32) * volume).astype(np.int16)


def normalize(pcm: np.ndarray, peak: float = 0.95) -> np.ndarray:
    """Raises (or lowers) the volume until the peak reaches `peak` of full scale."""
    maximum = np.abs(pcm).max() if len(pcm) else 0
    if not maximum:
        return pcm
    return np.clip(pcm.astype(np.float32) * (peak * 32767 / maximum), -32768, 32767).astype(np.int16)
