"""Kokoro on Windows and Linux: Kokoro-82M in ONNX (kokoro-onnx, Apache 2.0), a natural voice on
the CPU. Its model (int8, 88 MB) and voices (27 MB) download once into the cache folder's «models»
(pinned to a release and checked: server/models.py).

Voices by language (--voice, or settings «voice»: {"es": "em_alex"}): Spanish ef_dora (the
default), em_alex, em_santa; English af_heart (the default), af_bella, am_michael, bf_emma,
bm_george…; also French, Italian, Portuguese, Hindi, Japanese and Chinese. A name that isn't
Kokoro's (the Mac's «Mónica») gets the language's default.
"""

import logging
import threading

import numpy as np
from scipy.signal import resample_poly

import i18n
import models
from tts import RATE, Voice, register

log = logging.getLogger("tts")
FILES = ("kokoro-v1.0.int8.onnx", "voices-v1.0.bin")  # the model and its voices, in models.MODELS["kokoro"]
# Its language codes, and the default voice of each.
LANGUAGES = {"es": ("es", "ef_dora"), "en": ("en-us", "af_heart"), "fr": ("fr-fr", "ff_siwis"),
             "it": ("it", "if_sara"), "pt": ("pt-br", "pf_dora"), "hi": ("hi", "hf_alpha"),
             "ja": ("ja", "jf_alpha"), "zh": ("cmn", "zf_xiaobei")}
_model = None
_loading = threading.Lock()


def model():
    """Kokoro, loaded once (downloaded and checked the first time)."""
    global _model
    with _loading:
        if _model is None:
            from kokoro_onnx import Kokoro

            place = models.fetch("kokoro")
            _model = Kokoro(str(place / FILES[0]), str(place / FILES[1]))
        return _model


@register("kokoro")
class KokoroVoice(Voice):
    def __init__(self, voice=None, rate=None):
        super().__init__(voice, rate)
        self.lang, default = LANGUAGES.get(i18n.L.code, LANGUAGES["en"])
        if self.voice not in model().get_voices():
            self.voice = default  # the Mac's «Mónica»: the language's own here

    def synthesize(self, text: str) -> np.ndarray:
        speed = min(max((self.rate or 175) / 175, 0.5), 2.0)  # words per minute → its speed
        samples, rate = model().create(text, voice=self.voice, speed=speed, lang=self.lang)
        pcm = resample_poly(np.asarray(samples, np.float32), RATE // 1000, rate // 1000)
        return (np.clip(pcm, -1, 1) * 32767).astype(np.int16)

    def voices(self) -> list[str]:
        return sorted(model().get_voices())
