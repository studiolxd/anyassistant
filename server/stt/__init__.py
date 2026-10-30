"""Plugins de transcripción (voz → texto).

Un plugin es un módulo de este paquete con una clase registrada así:

    @registrar("nombre")
    class MiMotor(Transcriptor):
        def transcribir(self, audio): ...
"""

import numpy as np

from plugins import Registro

TASA = 16000  # todos los plugins reciben float32 mono a 16 kHz

_registro = Registro(__name__, __path__, "STT")
registrar = _registro.registrar
crear = _registro.crear
disponibles = _registro.disponibles


class Transcriptor:
    nombre = "?"

    def __init__(self, idioma: str = "es", modelo: str | None = None):
        self.idioma = idioma
        self.modelo = modelo

    def calentar(self):
        """Carga el modelo para que la primera frase no espere."""
        self.transcribir(np.zeros(TASA // 2, dtype=np.float32))

    def transcribir(self, audio: np.ndarray) -> str:
        raise NotImplementedError
