"""Kokoro on Windows and Linux: Kokoro-82M in ONNX (kokoro-onnx, Apache 2.0), a natural voice on
the CPU. Its model (int8, 88 MB) and voices (27 MB) download once into the cache folder's «models»
(pinned to a release and checked: server/models.py).

Voices by language (--voice, or settings «voice»: {"es": "em_alex"}): Spanish ef_dora (the
default), em_alex, em_santa; English af_heart (the default), af_bella, am_michael, bf_emma,
bm_george…; also French, Italian, Portuguese, Hindi, Japanese and Chinese. A name that isn't
Kokoro's (the Mac's «Mónica») gets the language's default. By voice, «pon la voz de Alex»
(the LLM's set_voice: the name after the prefix).
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
# The pinned voices file's, listed without loading the model; the first letter is the language (SPEAKS).
VOICES = ("af_alloy af_aoede af_bella af_heart af_jessica af_kore af_nicole af_nova af_river af_sarah af_sky "
          "am_adam am_echo am_eric am_fenrir am_liam am_michael am_onyx am_puck am_santa "
          "bf_alice bf_emma bf_isabella bf_lily bm_daniel bm_fable bm_george bm_lewis "
          "ef_dora em_alex em_santa ff_siwis hf_alpha hf_beta hm_omega hm_psi if_sara im_nicola "
          "jf_alpha jf_gongitsune jf_nezumi jf_tebukuro jm_kumo pf_dora pm_alex pm_santa "
          "zf_xiaobei zf_xiaoni zf_xiaoxiao zf_xiaoyi zm_yunjian zm_yunxi zm_yunxia zm_yunyang").split()
SPEAKS = {"a": "en", "b": "en", "e": "es", "f": "fr", "i": "it", "p": "pt", "h": "hi", "j": "ja", "z": "zh"}
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
        if self.voice not in VOICES:
            self.voice = default  # the Mac's «Mónica»: the language's own here

    def synthesize(self, text: str) -> np.ndarray:
        speed = min(max((self.rate or 175) / 175, 0.5), 2.0)  # words per minute → its speed
        samples, rate = model().create(text, voice=self.voice, speed=speed, lang=self.lang)
        pcm = resample_poly(np.asarray(samples, np.float32), RATE // 1000, rate // 1000)
        return (np.clip(pcm, -1, 1) * 32767).astype(np.int16)

    @classmethod
    def voices(cls, language: str) -> list[str]:
        default = LANGUAGES.get(language, (None, None))[1]  # the language's default first
        return sorted((v for v in VOICES if SPEAKS.get(v[0]) == language), key=lambda v: (v != default, v))

    @classmethod
    def label(cls, name: str) -> str:
        return name.partition("_")[2].replace("_", " ").title() or name  # ef_dora → Dora
