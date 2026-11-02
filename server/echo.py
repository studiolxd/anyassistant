"""Its own voice heard back through a device's microphone, told from a person talking over it.

The server knows exactly what it sends to each device (the PCM of its voice, its sounds) and when,
so there is no need for the device to capture anything: it keeps the loudness *envelope* of what it
sent in the last seconds (a Trail: log-RMS per 20 ms window, fifty numbers a second) and, when a
sentence is heard while it was speaking, compares the sentence's envelope with that trail (Judge).
Envelopes, not samples: the microphone hears the room's version of its voice (later, filtered,
quieter, mixed with the room), but its loudness rises and falls in step. The device's playback and
return delay is unknown (some 100–500 ms), so the alignment is searched over a range of lags.

- The same sound, quieter and later: it correlates (its echo). Someone else talking: it doesn't.
  Compared as amplitudes (not decibels): with synthetic voices its echo scores above 0.9 and a
  person over it below 0.75, a wider margin than in decibels (tests/test_own_voice.py).
- Nothing was playing: not judged (it can't be its echo).
- An onset of its output (silence → loud: a chime, the start of a sentence) vetoes a sentence
  starting in the ear right then: the first loud window of a sound isn't a person.

Pure functions, so tests can feed synthetic signals (tests/test_own_voice.py).
"""

import logging
import time

import numpy as np

import settings

log = logging.getLogger("echo")

HOP = 0.02  # seconds per envelope window (50 a second)
FLOOR = -60.0  # dBFS: anything quieter is silence
KEEP = 12.0  # seconds of its output kept, per device
LAG_MAX = 1.5  # seconds: the latest its voice can come back (playback, the room, the network: the
               # iPhone's, over Wi-Fi, can take more than a second)
MIN_SECONDS = 0.4  # at least this much of its output under the sentence, to judge it
THRESHOLD = 0.8  # correlation from which a sentence is its own echo (settings «echo_match»)
CLEAR = 0.5  # below this, clearly a person: it stops at once (between both, its words decide)
LOUD = -35.0  # dBFS: its output counts as playing above this
ONSET_SECONDS = 0.8  # after its output starts from silence, a sentence can't start in the ear
ONSET_QUIET = 0.3  # seconds of silence before a start for it to count as an onset


def envelope(samples: np.ndarray, rate: int) -> np.ndarray:
    """The loudness of `samples` (float, -1…1; int16 is scaled) per HOP seconds, in dBFS, floored."""
    samples = np.asarray(samples)
    if samples.dtype == np.int16:
        samples = samples.astype(np.float32) / 32768
    n = max(1, int(rate * HOP))
    frames = len(samples) // n
    if frames == 0:
        return np.zeros(0, np.float32)
    windows = samples[: frames * n].astype(np.float32).reshape(frames, n)
    rms = np.sqrt(np.mean(np.square(windows), axis=1))
    return np.maximum(20 * np.log10(rms + 1e-9), FLOOR).astype(np.float32)


def correlation(a: np.ndarray, b: np.ndarray) -> float:
    """Normalized correlation of two envelopes (-1…1); 0 if either is flat."""
    a, b = np.asarray(a, np.float64), np.asarray(b, np.float64)
    n = min(len(a), len(b))
    if n < 2:
        return 0.0
    a, b = a[:n] - np.mean(a[:n]), b[:n] - np.mean(b[:n])
    norm = float(np.sqrt(np.sum(a * a) * np.sum(b * b)))
    return float(np.sum(a * b) / norm) if norm > 1e-9 else 0.0


class Trail:
    """The envelope of what was sent to one device, on a timeline (absolute seconds): add() what is
    played and when it starts playing; window() reads any span (silence where nothing was sent)."""

    def __init__(self):
        self.frames = np.zeros(0, np.float32)
        self.start = None  # when frames[0] plays

    @property
    def end(self) -> float:
        return (self.start or 0.0) + len(self.frames) * HOP

    def add(self, pcm: np.ndarray, at: float, now: float | None = None):
        """`pcm` (48 kHz int16) starts playing at `at`. Kept: from KEEP seconds before now (or
        `at`, if earlier) on, whatever is queued after it: a long answer is sent at once, so
        what plays now must not be dropped for what plays later."""
        env = envelope(pcm, 48000)
        if not len(env):
            return
        if self.start is None or at - self.end > KEEP:
            self.frames, self.start = env, at
        else:
            index = int(round((at - self.start) / HOP))
            if index >= len(self.frames):
                gap = np.full(index - len(self.frames), FLOOR, np.float32)
                self.frames = np.concatenate([self.frames, gap, env])
            else:  # overlapping what was queued (it shouldn't): the new one wins from there
                self.frames = np.concatenate([self.frames[:max(0, index)], env])
                if index < 0:
                    self.start = at
        since = min(time.time() if now is None else now, at) - KEEP
        extra = int((since - self.start) / HOP)
        if extra > 0:
            self.frames = self.frames[extra:]
            self.start += extra * HOP

    def cut(self, at: float | None = None):
        """What was to play after `at` (now) won't: it was stopped."""
        if self.start is None:
            return
        keep = int(round(((at if at is not None else time.time()) - self.start) / HOP))
        if keep < len(self.frames):
            self.frames = self.frames[:max(0, keep)]

    def window(self, t0: float, t1: float) -> np.ndarray:
        """The envelope from t0 to t1: FLOOR wherever nothing was sent."""
        count = max(0, int(round((t1 - t0) / HOP)))
        out = np.full(count, FLOOR, np.float32)
        if self.start is None or count == 0:
            return out
        first = int(round((t0 - self.start) / HOP))
        lo, hi = max(0, first), min(len(self.frames), first + count)
        if hi > lo:
            out[lo - first: hi - first] = self.frames[lo:hi]
        return out

    def playing(self, t0: float, t1: float, seconds: float = MIN_SECONDS) -> bool:
        """Whether its output was loud for at least `seconds` within t0…t1."""
        return float(np.sum(self.window(t0, t1) > LOUD)) * HOP >= seconds

    def onset(self, now: float) -> bool:
        """Whether its output started from silence in the last ONSET_SECONDS."""
        before = self.window(now - ONSET_SECONDS - ONSET_QUIET, now - ONSET_SECONDS)
        since = self.window(now - ONSET_SECONDS, now)
        if not len(since):
            return False
        loud = np.flatnonzero(since > LOUD)
        if not len(loud):
            return False
        first = loud[0]
        quiet = np.concatenate([before, since[:first]])[-int(ONSET_QUIET / HOP):]
        return len(quiet) > 0 and bool(np.max(quiet) < LOUD - 10)


def amplitude(env: np.ndarray) -> np.ndarray:
    """An envelope in dB as amplitudes (0…1): what is compared."""
    return np.power(10.0, np.asarray(env, np.float64) / 20)


def match(heard: np.ndarray, trail: Trail, end: float, lag_max: float = LAG_MAX) -> tuple[float, float]:
    """How much a sentence's envelope (ending at `end`) looks like the trail, searching the lag:
    (correlation, lag in seconds). (0, 0) if nothing was playing under it."""
    duration = len(heard) * HOP
    if not trail.playing(end - duration - lag_max, end):
        return 0.0, 0.0
    best, at = 0.0, 0.0
    wanted = amplitude(heard)
    for lag in np.arange(0.0, lag_max + HOP / 2, HOP):
        if not trail.playing(end - duration - lag, end - lag):
            continue
        score = correlation(wanted, amplitude(trail.window(end - duration - lag, end - lag)))
        if score > best:
            best, at = score, float(lag)
    return best, at


def threshold() -> float:
    found = settings.get("echo_match")
    return float(found) if found is not None else THRESHOLD


class Judge:
    """For an ear: whether a sentence heard while it spoke is its own echo, against the trails of
    every device playing (its own and the others in the room: `trails()` gives them, its own first)."""

    def __init__(self, trails):
        self.trails = trails
        self.last = None  # (score, lag) of the last sentence judged, for the log and tests

    def is_echo(self, audio16: np.ndarray, end: float) -> bool:
        heard = envelope(audio16, 16000)
        self.last = None
        for trail in self.trails():
            score, lag = match(heard, trail, end)
            if self.last is None or score > self.last[0]:
                self.last = (score, lag)
            if score >= threshold():
                log.info("its own echo (%.2f at %d ms)", score, lag * 1000)
                return True
        if self.last:
            log.info("not its echo (%.2f at %d ms)", self.last[0], self.last[1] * 1000)
        return False

    def clearly_a_person(self) -> bool:
        """The last sentence judged doesn't look like its output at all (below CLEAR): a person."""
        return self.last is None or self.last[0] < CLEAR

    def onset(self, now: float | None = None) -> bool:
        now = now or time.time()
        return any(trail.onset(now) for trail in self.trails())
