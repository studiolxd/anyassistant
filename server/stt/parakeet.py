"""Parakeet TDT v3 de NVIDIA en MLX: multilingüe (español incluido) y mucho más
rápido que Whisper con frases cortas, porque no rellena el audio hasta 30 s.

Detecta el idioma solo y no se le puede forzar: con frases cortas o voces raras
a veces se va al inglés («¿Qué hora es?» → «Koda is a very good idea»). Si el
resultado parece de otro idioma y se pidió español, esa frase se repite con
Whisper (--stt-modelo no le afecta; el respaldo es RESPALDO); y si Whisper
devuelve una de sus alucinaciones típicas («Gracias.»), se descarta.
"""

import logging
import re

import numpy as np

from stt import GPU, Transcriptor, registrar
from texto import normalizar

log = logging.getLogger("stt")

RESPALDO = "mlx-community/whisper-large-v3-turbo"
# Palabras muy inglesas y nada españolas (sin «a», «me», «no»…, que lo son las dos).
INGLES = {
    "the", "is", "are", "was", "i", "you", "it", "its", "of", "and", "to", "this",
    "that", "very", "good", "done", "idea", "what", "okay", "yeah", "oh", "hmm",
    "mm", "so", "my", "we", "they", "be", "do", "have", "with", "for", "on", "in",
    "see", "yes", "true", "s",  # «That's» → that + s
}
# Lo que Whisper se inventa con ruido en español: si Parakeet no entendió nada y
# Whisper devuelve esto, es que no había nada que entender.
ALUCINACIONES = {"gracias", "muchas gracias", "gracias por ver", "subtitulos realizados por la comunidad de amara org"}


def parece_ingles(texto: str) -> bool:
    """Inglés o, en general, no español: «That's true.», «See», «tři»."""
    if re.search(r"[^\W\d_a-záéíóúüñ]", texto.lower()):
        return True  # letras que no existen en español («ř», «ø»…)
    palabras = normalizar(texto)
    return bool(palabras) and sum(p in INGLES for p in palabras) / len(palabras) >= 0.3


@registrar("parakeet")
class Parakeet(Transcriptor):
    def __init__(self, idioma="es", modelo=None):
        super().__init__(idioma, modelo or "mlx-community/parakeet-tdt-0.6b-v3")
        import mlx.core as mx
        from parakeet_mlx import from_pretrained
        from parakeet_mlx.audio import get_logmel

        self._mx = mx
        self._logmel = get_logmel
        self._modelo = from_pretrained(self.modelo)

    def calentar(self):
        super().calentar()
        if self.idioma != "en":
            self._respaldo(np.zeros(8000, dtype=np.float32))

    def transcribir(self, audio: np.ndarray) -> str:
        with GPU:
            mel = self._logmel(self._mx.array(audio), self._modelo.preprocessor_config)
            texto = self._modelo.generate(mel)[0].text.strip()
        if self.idioma != "en" and parece_ingles(texto):
            corregido = self._respaldo(audio)
            if " ".join(normalizar(corregido)) in ALUCINACIONES:
                log.info("parakeet: «%s»; Whisper se lo inventa («%s»): descartado", texto, corregido)
                return ""
            log.info("parakeet se fue a otro idioma («%s»); con Whisper: «%s»", texto, corregido)
            return corregido
        return texto

    def _respaldo(self, audio: np.ndarray) -> str:
        from stt.mlx_whisper import transcribir_mlx

        return transcribir_mlx(audio, RESPALDO, self.idioma)
