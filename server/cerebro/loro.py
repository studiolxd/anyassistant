"""Fase 1: el loro. Graba lo que dices y lo repite cuando terminas.

Mientras repite (y un poco después) no escucha, para no oírse a sí mismo:
el mismo semidúplex que usará el asistente si la cancelación de eco no basta.
"""

import time

import numpy as np

from audio import TASA

UMBRAL = 600  # RMS a partir del cual se considera voz
SILENCIO = 0.8  # segundos de silencio que cierran la frase
MAXIMO = 10  # segundos máximos de grabación
GUARDA = 0.7  # segundos sin escuchar tras repetir (latencia + reverberación)


class Loro:
    def __init__(self, altavoz, enviar):
        self.altavoz = altavoz
        self.enviar = enviar
        self.trozos = []
        self.silencio = 0.0
        self.estado = None
        self._estado("escuchando")

    def _estado(self, estado: str):
        if estado != self.estado:
            self.estado = estado
            self.enviar({"tipo": "estado", "estado": estado})

    def oir(self, pcm: np.ndarray):
        if self.altavoz.hablando or time.time() - self.altavoz.ultimo_sonido < GUARDA:
            return
        if self.estado == "repitiendo":
            self._estado("escuchando")

        rms = float(np.sqrt(np.mean(pcm.astype(np.float32) ** 2)))

        if rms > UMBRAL:
            self.silencio = 0.0
            self._estado("grabando")
        if self.estado != "grabando":
            return

        self.trozos.append(pcm)
        if rms <= UMBRAL:
            self.silencio += len(pcm) / TASA
        duracion = sum(len(t) for t in self.trozos) / TASA
        if self.silencio >= SILENCIO or duracion >= MAXIMO:
            self.altavoz.reproducir(np.concatenate(self.trozos))
            self.trozos = []
            self.silencio = 0.0
            self._estado("repitiendo")
