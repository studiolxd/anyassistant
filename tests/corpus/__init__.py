"""The audio corpus: a fixed selection of public recordings (never anyone's own voice) to measure
the listening pipeline with many voices (docs/corpus.md).

- cases.json: the manifest. Each case says where its audio comes from (the dataset, the file,
  the revision and its SHA-256), its language, the expected transcript (normalised), its speaker,
  and what is mixed in (a noise, a room's impulse response, the SNR). Nothing of the audio is in
  git: `bin/anyassistant corpus fetch` (fetch.py) downloads exactly that selection into the cache
  (paths.CACHE/corpus), checks every hash and builds the mixed cases.
- run.py measures: transcription (WER per engine), sentence ends (the «silence» option), voice
  activity in noise (false starts) and who is speaking (voice_match, its lower bound, the EER).
- baseline.json: the last accepted metrics (tests/test_corpus.py fails when one gets clearly worse;
  `bin/anyassistant corpus baseline` writes it anew on purpose).

This module: the manifest, where things are, audio in and out, mixing and the text metrics. Only
numpy and scipy (and PyAV, which aiortc brings, to decode MP3, FLAC and Opus).
"""

import io
import json
import re
import unicodedata
import wave
from pathlib import Path

import numpy as np
from scipy.signal import fftconvolve, resample_poly

import paths

RATE = 16000  # every case is 16 kHz mono, what the ear's STT and VAD work with
HERE = Path(__file__).resolve().parent
MANIFEST = HERE / "cases.json"
BASELINE = HERE / "baseline.json"

# Around each clip, so a sentence has room to start and to end as it would in a room: silence
# (a speech case) or the same noise (a mixed one). The tail is longer than any «silence» tried.
LEAD = 0.5
LEAD_NOISE = 3.0  # noise before the speech, so the ear's noise floor settles as in a real room
TAIL = 1.5


def folder() -> Path:
    """Where the corpus lives on this computer: the cache's «corpus»."""
    return paths.CACHE / "corpus"


def cases_folder() -> Path:
    return folder() / "cases"


def raw_folder() -> Path:
    return folder() / "raw"


def manifest(path: Path = MANIFEST) -> dict:
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def by_id(found: dict) -> dict:
    return {c["id"]: c for c in found["cases"]}


def ready(found: dict | None = None) -> bool:
    """Whether every case's audio is in the cache (fetch.py done)."""
    found = found or manifest()
    return all(case_path(c["id"]).exists() for c in found["cases"] if c["kind"] != "rir")


def missing(found: dict | None = None) -> list[str]:
    found = found or manifest()
    return [c["id"] for c in found["cases"] if c["kind"] != "rir" and not case_path(c["id"]).exists()]


def case_path(case_id: str) -> Path:
    return cases_folder() / f"{case_id}.wav"


# --- Audio in and out ---

def read_wav(path: Path) -> np.ndarray:
    """A 16 kHz mono 16-bit WAV as float32 (-1–1)."""
    with wave.open(str(path)) as w:
        if w.getframerate() != RATE or w.getnchannels() != 1 or w.getsampwidth() != 2:
            raise ValueError(f"{path}: not 16 kHz mono 16-bit")
        return np.frombuffer(w.readframes(w.getnframes()), np.int16).astype(np.float32) / 32768


def write_wav(path: Path, audio: np.ndarray):
    path.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(RATE)
        w.writeframes((np.clip(audio, -1, 1) * 32767).astype(np.int16).tobytes())


def decode(data: bytes, name: str = "") -> np.ndarray:
    """Any audio file's bytes (WAV, MP3, FLAC, Opus…) as 16 kHz mono float32."""
    if data[:4] == b"RIFF":
        try:
            return _decode_wav(data)
        except (wave.Error, ValueError):
            pass  # a WAV PyAV can read (float, 24-bit…)
    import av

    with av.open(io.BytesIO(data)) as container:
        stream = container.streams.audio[0]
        resampler = av.AudioResampler(format="flt", layout="mono", rate=RATE)
        pieces = []
        for frame in container.decode(stream):
            for out in resampler.resample(frame):
                pieces.append(out.to_ndarray().reshape(-1))
        for out in resampler.resample(None):  # what the resampler still holds
            pieces.append(out.to_ndarray().reshape(-1))
    if not pieces:
        raise ValueError(f"{name or 'audio'}: nothing decoded")
    return np.concatenate(pieces).astype(np.float32)


def _decode_wav(data: bytes) -> np.ndarray:
    with wave.open(io.BytesIO(data)) as w:
        rate, channels, width = w.getframerate(), w.getnchannels(), w.getsampwidth()
        frames = w.readframes(w.getnframes())
    if width == 2:
        audio = np.frombuffer(frames, np.int16).astype(np.float32) / 32768
    elif width == 4:
        audio = np.frombuffer(frames, np.int32).astype(np.float32) / 2147483648
    elif width == 1:
        audio = (np.frombuffer(frames, np.uint8).astype(np.float32) - 128) / 128
    else:
        raise ValueError("unusual sample width")
    if channels > 1:
        audio = audio.reshape(-1, channels).mean(axis=1)
    return to_rate(audio, rate)


def to_rate(audio: np.ndarray, rate: int) -> np.ndarray:
    if rate == RATE:
        return audio.astype(np.float32)
    from math import gcd

    g = gcd(rate, RATE)
    return resample_poly(audio.astype(np.float64), RATE // g, rate // g).astype(np.float32)


# --- Mixing ---

def rms(audio: np.ndarray) -> float:
    return float(np.sqrt(np.mean(np.square(audio)))) if len(audio) else 0.0


def speech_level(audio: np.ndarray, frame: float = 0.02) -> float:
    """The RMS of the louder half of a clip's 20 ms frames: what the voice itself measures, not
    the silence around it (a clip is a third silence)."""
    size = int(frame * RATE)
    count = len(audio) // size
    if count < 2:
        return rms(audio)
    frames = audio[:count * size].reshape(count, size)
    levels = np.sqrt(np.mean(np.square(frames), axis=1))
    loud = levels[levels >= np.median(levels)]
    return float(np.sqrt(np.mean(np.square(loud)))) if len(loud) else rms(audio)


def segment(noise: np.ndarray, start: float, seconds: float) -> np.ndarray:
    """`seconds` of a noise recording from `start`, repeated if it is shorter."""
    wanted = int(seconds * RATE)
    begin = int(start * RATE) % max(1, len(noise))
    piece = noise[begin:begin + wanted]
    while len(piece) < wanted:
        piece = np.concatenate([piece, noise[:wanted - len(piece)]])
    return piece.astype(np.float32)


def pad(speech: np.ndarray, lead: float = LEAD, tail: float = TAIL) -> np.ndarray:
    """A speech clip with silence before and after, as the ear hears a sentence in a quiet room."""
    return np.concatenate([np.zeros(int(lead * RATE), np.float32), speech, np.zeros(int(tail * RATE), np.float32)])


def mix(speech: np.ndarray, noise: np.ndarray, snr_db: float, start: float = 0.0) -> np.ndarray:
    """The speech over the noise at `snr_db` (the voice's level against the noise's RMS), with
    LEAD_NOISE seconds of noise alone before it and TAIL after: the room was already noisy."""
    total = int(LEAD_NOISE * RATE) + len(speech) + int(TAIL * RATE)
    background = segment(noise, start, total / RATE)
    level = rms(background)
    if level > 0:
        background = background * (speech_level(speech) / (10 ** (snr_db / 20)) / level)
    out = background.copy()
    begin = int(LEAD_NOISE * RATE)
    out[begin:begin + len(speech)] += speech
    peak = float(np.max(np.abs(out))) if len(out) else 0.0
    return (out / peak * 0.95 if peak > 0.95 else out).astype(np.float32)


def reverberate(speech: np.ndarray, rir: np.ndarray) -> np.ndarray:
    """The speech as heard in a room: convolved with its impulse response, kept at the same level
    (the direct path first, so the words aren't delayed)."""
    rir = rir.astype(np.float64)
    direct = int(np.argmax(np.abs(rir)))
    rir = rir[direct:]
    wet = fftconvolve(speech.astype(np.float64), rir)[:len(speech)]
    dry, now = speech_level(speech), speech_level(wet.astype(np.float32))
    if now > 0:
        wet = wet * (dry / now)
    peak = float(np.max(np.abs(wet))) if len(wet) else 0.0
    return (wet / peak * 0.95 if peak > 0.95 else wet).astype(np.float32)


# --- Text ---

_PUNCTUATION = re.compile(r"[^\w\s]|_", re.UNICODE)


def normalise(text: str) -> str:
    """How a transcript is compared: lowercase, no punctuation, no accents (but ñ stays), one
    space between words. «¿Qué hora es?» → «que hora es»."""
    text = unicodedata.normalize("NFKC", text or "").lower()
    text = text.replace("ñ", "\0")
    text = unicodedata.normalize("NFD", text)
    text = "".join(c for c in text if not unicodedata.combining(c)).replace("\0", "ñ")
    text = _PUNCTUATION.sub(" ", text.replace("'", " ").replace("-", " "))
    return " ".join(text.split())


def edits(reference: list, hypothesis: list) -> int:
    """Word errors (substitutions, deletions and insertions) between two word lists."""
    previous = list(range(len(hypothesis) + 1))
    for i, word in enumerate(reference, 1):
        current = [i]
        for j, other in enumerate(hypothesis, 1):
            current.append(min(previous[j] + 1, current[j - 1] + 1, previous[j - 1] + (word != other)))
        previous = current
    return previous[-1]


def wer(reference: str, hypothesis: str) -> float:
    """Word error rate, in % of the reference's words (both normalised); 0 when both are empty."""
    ref, hyp = normalise(reference).split(), normalise(hypothesis).split()
    if not ref:
        return 0.0 if not hyp else 100.0
    return 100.0 * edits(ref, hyp) / len(ref)


def corpus_wer(pairs: list[tuple[str, str]]) -> float:
    """The WER of many sentences together: errors over all the reference words."""
    errors = words = 0
    for reference, hypothesis in pairs:
        ref, hyp = normalise(reference).split(), normalise(hypothesis).split()
        errors += edits(ref, hyp) if ref else len(hyp)
        words += len(ref)
    return round(100.0 * errors / words, 2) if words else 0.0
