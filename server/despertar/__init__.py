"""Plugins de palabra de activación.

Un plugin es un módulo de este paquete con una clase registrada así:

    @registrar("nombre")
    class MiDespertador(Despertador):
        def escuchar(self, audio): ...   # float32 mono 16 kHz → bool
        def reiniciar(self): ...

Recibe el audio en trozos de cualquier tamaño y devuelve True en el trozo en
que reconoce la palabra. Con --despertar ninguno se escucha todo, sin palabra.

Opcional: si el plugin ya oyó la frase entera ("Hey Jarvis, ¿qué hora es?"),
la deja en self.frase_oida (float32 16 kHz) y el oído la transcribe sin
esperar otra; y quitar(texto) le quita la palabra al texto transcrito.
"""

import numpy as np

from plugins import Registro

TASA = 16000

_registro = Registro(__name__, __path__, "despertador")
registrar = _registro.registrar
crear = _registro.crear
disponibles = _registro.disponibles


class Despertador:
    nombre = "?"
    frase = "?"  # cómo se dice, para mostrarlo en la pantalla
    continuo = False  # True si necesita oír también mientras está despierto

    def __init__(self, palabra: str | None = None, umbral: float = 0.5):
        self.palabra = palabra
        self.umbral = umbral

    def escuchar(self, audio: np.ndarray) -> bool:
        raise NotImplementedError

    def reiniciar(self):
        pass
