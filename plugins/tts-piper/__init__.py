"""Piper: a lighter voice than Kokoro, for a Raspberry Pi (and Windows, Linux, the Mac): piper-tts
(VITS in ONNX, espeak-ng inside its wheel) on the CPU. Each voice is its own model (~63 MB;
carlfm, 28 MB, the lightest), downloaded the first time it speaks into the cache folder's
«models», pinned and checked (server/models.py, «piper-<voice>»).

Voices (--voice, or settings «voice»: {"es": "es_MX-claude-high"}; by voice, «pon la voz de
Claude»): Spanish es_ES-davefx-medium (the default), es_ES-carlfm-x_low, es_MX-claude-high,
es_MX-ald-medium, es_AR-daniela-high; English en_US-lessac-medium (the default), en_US-amy-medium,
en_US-ryan-medium, en_GB-alba-medium, en_GB-alan-medium. A name that isn't one of these (the
Mac's «Mónica») gets the language's default.
"""

import threading

import numpy as np
from scipy.signal import resample_poly

import i18n
import models
from tts import RATE, Voice, register

VOICES = [m.removeprefix("piper-") for m in models.MODELS if m.startswith("piper-")]  # «es_ES-davefx-medium»
DEFAULTS = {"es": "es_ES-davefx-medium", "en": "en_US-lessac-medium"}
_loaded: dict = {}  # voice → its PiperVoice, loaded once
_loading = threading.Lock()


def load(voice: str):
    """A voice's model, loaded once (downloaded and checked the first time)."""
    with _loading:
        if voice not in _loaded:
            from piper import PiperVoice

            place = models.fetch("piper-" + voice)
            _loaded[voice] = PiperVoice.load(place / f"{voice}.onnx", place / f"{voice}.onnx.json")
        return _loaded[voice]


@register("piper")
class PiperTTS(Voice):
    def __init__(self, voice=None, rate=None):
        super().__init__(voice, rate)
        if self.voice not in VOICES:
            self.voice = DEFAULTS.get(i18n.L.code, DEFAULTS["en"])  # the Mac's «Mónica»: the language's own here

    def synthesize(self, text: str) -> np.ndarray:
        from piper import SynthesisConfig

        piper = load(self.voice)
        # Words per minute → how long each sound lasts (Kokoro's 175 as the voice's own)
        config = SynthesisConfig(length_scale=min(max(175 / self.rate, 0.5), 2.0) if self.rate else None)
        chunks = [chunk.audio_float_array for chunk in piper.synthesize(text, syn_config=config)]  # one per sentence
        if not chunks:
            return np.zeros(0, np.int16)
        rate = piper.config.sample_rate  # 22050, 16000…
        divisor = np.gcd(rate, RATE)
        pcm = resample_poly(np.concatenate(chunks), RATE // divisor, rate // divisor)
        return (np.clip(pcm, -1, 1) * 32767).astype(np.int16)

    @classmethod
    def voices(cls, language: str) -> list[str]:
        default = DEFAULTS.get(language)
        return sorted((v for v in VOICES if v.split("_")[0] == language), key=lambda v: v != default)

    @classmethod
    def label(cls, name: str) -> str:
        parts = name.split("-")
        return parts[1].replace("_", " ").title() if len(parts) == 3 else name  # es_MX-claude-high → Claude
