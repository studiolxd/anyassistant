"""NVIDIA's Parakeet TDT v3 on Windows and Linux: the Mac's Parakeet (stt-parakeet) in ONNX
(onnx-asr, int8 on the CPU: about 650 MB, downloaded once). Multilingual and fast on short
sentences.

As on the Mac, it detects the language by itself and sometimes drifts into English with short
sentences: then that sentence is redone with Whisper (faster-whisper, FALLBACK), and one of
Whisper's typical hallucinations for the language («Gracias.») is dropped.
"""

import logging

import numpy as np

import i18n
import settings
from plugins.stt_faster_whisper import transcribe_fw
from plugins.stt_parakeet import wrong_language
from stt import RATE, Transcriber, register
from text import words

log = logging.getLogger("stt")
FALLBACK = "small"
MODEL = "nemo-parakeet-tdt-0.6b-v3"


@register("parakeet-onnx")
class ParakeetOnnx(Transcriber):
    def __init__(self, language="en", model=None):
        super().__init__(language, model or MODEL)
        import onnx_asr

        self._model = onnx_asr.load_model(self.model, quantization="int8")

    def warm_up(self):
        super().warm_up()
        if self.language != "en":
            transcribe_fw(np.zeros(8000, dtype=np.float32), FALLBACK, self.language)

    def transcribe(self, audio: np.ndarray) -> str:
        text = str(self._model.recognize(audio.astype(np.float32), sample_rate=RATE)).strip()
        if self.language != "en" and wrong_language(text):
            corrected = transcribe_fw(audio, FALLBACK, self.language)
            if " ".join(words(corrected)) in i18n.L.list("stt.fallback_hallucinations"):
                log.info("parakeet: «%s»; Whisper made it up («%s»): dropped", settings.private(text), settings.private(corrected))
                return ""
            log.info("parakeet drifted to another language («%s»); with Whisper: «%s»",
                     settings.private(text), settings.private(corrected))
            return corrected
        return text
