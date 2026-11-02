"""Audio as 16-bit mono PCM at 48 kHz, in 20 ms chunks.

- to_mono: converts what arrives from the microphone (decoded Opus) to that format.
- Speaker: the outgoing track; plays whatever is queued, silence otherwise.
"""

import asyncio
import fractions
import time
import wave
from pathlib import Path

import numpy as np
from aiortc import MediaStreamTrack
from av import AudioFrame

import echo

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
        self.trail = echo.Trail()  # the loudness of what went out and when: to know its own echo

    @property
    def speaking(self) -> bool:
        return len(self._queue) > 0

    def play(self, pcm: np.ndarray) -> float:
        """Queues it; returns when it starts playing (after what is queued)."""
        pcm = pcm.astype(np.int16)
        starts = time.time() + len(self._queue) / RATE
        self.trail.add(pcm, starts)
        self._queue = np.concatenate([self._queue, pcm])
        return starts

    def stop(self):
        self._queue = np.zeros(0, dtype=np.int16)
        self.trail.cut()

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


# --- WAV files (sounds of themes and plugins) ---

_sounds: dict[tuple[str, float], np.ndarray | None] = {}


def wav(file: Path) -> np.ndarray | None:
    """A 16-bit WAV as 48 kHz mono PCM (kept while the file doesn't change), or None."""
    if not file.exists():
        return None
    key = (str(file), file.stat().st_mtime)
    if key not in _sounds:
        _sounds[key] = _read_wav(file)
    return _sounds[key]


def wav_bytes(pcm: np.ndarray) -> bytes:
    """48 kHz mono PCM as a 16-bit WAV file's bytes."""
    import io

    out = io.BytesIO()
    with wave.open(out, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(48000)
        w.writeframes(np.asarray(pcm, np.int16).tobytes())
    return out.getvalue()


def _read_wav(file: Path) -> np.ndarray | None:
    try:
        with wave.open(str(file)) as w:
            if w.getsampwidth() != 2:
                return None
            pcm = np.frombuffer(w.readframes(w.getnframes()), np.int16)
            if w.getnchannels() == 2:
                pcm = pcm.reshape(-1, 2).mean(axis=1).astype(np.int16)
            rate = w.getframerate()
        if rate != 48000:
            from scipy.signal import resample_poly
            from math import gcd

            g = gcd(48000, rate)
            pcm = resample_poly(pcm.astype(np.float32), 48000 // g, rate // g).astype(np.int16)
        return pcm[: 48000 * 10]  # at most 10 s
    except (OSError, wave.Error, EOFError):
        return None


# --- Checking a theme ---
