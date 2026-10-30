"""Plugins de voz (texto → audio).

Un plugin es un módulo de este paquete con una clase registrada así:

    @registrar("nombre")
    class MiVoz(Voz):
        def sintetizar(self, texto): ...   # → int16 mono a 48 kHz

sintetizar() se llama en un hilo aparte, frase a frase.
"""

import numpy as np

from plugins import Registro

TASA = 48000  # lo que espera el Altavoz

_registro = Registro(__name__, __path__, "TTS")
registrar = _registro.registrar
crear = _registro.crear
disponibles = _registro.disponibles


class Voz:
    nombre = "?"

    def __init__(self, voz: str | None = None, velocidad: int | None = None):
        self.voz = voz
        self.velocidad = velocidad

    def calentar(self):
        self.sintetizar("Hola.")

    def sintetizar(self, texto: str) -> np.ndarray:
        raise NotImplementedError

    def cerrar(self):
        """Al parar el servidor: libera procesos."""
