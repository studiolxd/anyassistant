"""NVIDIA's Parakeet TDT v3 on MLX: multilingual and much faster than Whisper on
short sentences, because it doesn't pad the audio to 30 s.

It detects the language by itself and cannot be forced: with short sentences or
odd voices it sometimes drifts into English («¿Qué hora es?» → «Koda is a very
good idea»). If the result looks like another language than the one requested,
that sentence is redone with Whisper (FALLBACK; --stt-model doesn't affect it);
and if Whisper returns one of its typical hallucinations for that language
(locale stt.fallback_hallucinations, e.g. «Gracias.»), it is dropped.
"""

import logging
import re

import numpy as np

import i18n
import settings
from stt import GPU, Transcriber, register
from text import words

log = logging.getLogger("stt")

FALLBACK = "mlx-community/whisper-large-v3-turbo"
# Very English words that are not words in other languages (no «a», «me», «no»…).
ENGLISH = {
    "the", "is", "are", "was", "i", "you", "it", "its", "of", "and", "to", "this",
    "that", "very", "good", "done", "idea", "what", "okay", "yeah", "oh", "hmm",
    "mm", "so", "my", "we", "they", "be", "do", "have", "with", "for", "on", "in",
    "see", "yes", "true", "s",  # «That's» → that + s
}


def wrong_language(text: str) -> bool:
    """English or, more generally, not the active language: «That's true.», «See», «tři»."""
    letters = re.escape(i18n.L("stt.letters"))
    if re.search(rf"[^\W\d_a-z{letters}]", text.lower()):
        return True  # letters the language doesn't have («ř», «ø»…)
    if i18n.L.stt_language == "en":
        return False
    found = words(text)
    return bool(found) and sum(w in ENGLISH for w in found) / len(found) >= 0.3


@register("parakeet")
class Parakeet(Transcriber):
    def __init__(self, language="en", model=None):
        super().__init__(language, model or "mlx-community/parakeet-tdt-0.6b-v3")
        import mlx.core as mx
        from parakeet_mlx import from_pretrained
        from parakeet_mlx.audio import get_logmel

        self._mx = mx
        self._logmel = get_logmel
        self._model = from_pretrained(self.model)

    def warm_up(self):
        super().warm_up()
        if self.language != "en":
            self._fallback(np.zeros(8000, dtype=np.float32))

    def transcribe(self, audio: np.ndarray) -> str:
        with GPU:
            mel = self._logmel(self._mx.array(audio), self._model.preprocessor_config)
            text = self._model.generate(mel)[0].text.strip()
        if self.language != "en" and wrong_language(text):
            corrected = self._fallback(audio)
            if " ".join(words(corrected)) in i18n.L.list("stt.fallback_hallucinations"):
                log.info("parakeet: «%s»; Whisper made it up («%s»): dropped", settings.private(text), settings.private(corrected))
                return ""
            log.info("parakeet drifted to another language («%s»); with Whisper: «%s»",
                     settings.private(text), settings.private(corrected))
            return corrected
        return text

    def _fallback(self, audio: np.ndarray) -> str:
        from plugins.stt_mlx_whisper import transcribe_mlx

        return transcribe_mlx(audio, FALLBACK, self.language)
