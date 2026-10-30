"""Audio en PCM mono 16 bits a 48 kHz, en trozos de 20 ms.

- a_mono: convierte lo que llega del micro (Opus decodificado) a ese formato.
- Altavoz: pista de salida; reproduce lo que se le encole y silencio si no hay nada.
"""

import asyncio
import fractions
import time

import numpy as np
from aiortc import MediaStreamTrack
from av import AudioFrame

TASA = 48000
MUESTRAS = 960  # 20 ms


def a_mono(frame) -> np.ndarray:
    datos = frame.to_ndarray()
    canales = len(frame.layout.channels)
    if frame.format.is_planar:
        mono = datos.mean(axis=0)
    else:
        mono = datos.reshape(-1, canales).mean(axis=1)
    return mono.astype(np.int16)


class Altavoz(MediaStreamTrack):
    kind = "audio"

    def __init__(self):
        super().__init__()
        self._cola = np.zeros(0, dtype=np.int16)
        self._inicio = None
        self._pts = 0
        self.ultimo_sonido = 0.0  # cuándo salió la última muestra con sonido

    @property
    def hablando(self) -> bool:
        return len(self._cola) > 0

    def reproducir(self, pcm: np.ndarray):
        self._cola = np.concatenate([self._cola, pcm.astype(np.int16)])

    def callar(self):
        self._cola = np.zeros(0, dtype=np.int16)

    async def recv(self) -> AudioFrame:
        if self._inicio is None:
            self._inicio = time.time()
        espera = self._inicio + self._pts / TASA - time.time()
        if espera > 0:
            await asyncio.sleep(espera)

        trozo, self._cola = self._cola[:MUESTRAS], self._cola[MUESTRAS:]
        if len(trozo):
            self.ultimo_sonido = time.time()
        if len(trozo) < MUESTRAS:
            trozo = np.pad(trozo, (0, MUESTRAS - len(trozo)))

        frame = AudioFrame.from_ndarray(trozo.reshape(1, -1), format="s16", layout="mono")
        frame.sample_rate = TASA
        frame.pts = self._pts
        frame.time_base = fractions.Fraction(1, TASA)
        self._pts += MUESTRAS
        return frame


def pitido() -> np.ndarray:
    """Dos notas cortas ascendentes: «te escucho»."""
    notas = []
    for frecuencia in (880, 1320):
        t = np.arange(int(0.09 * TASA)) / TASA
        envolvente = np.minimum(1, np.minimum(t, t[::-1]) / 0.01)  # sin chasquidos
        notas.append(np.sin(2 * np.pi * frecuencia * t) * envolvente * 0.5 * 32767)
    return np.concatenate(notas).astype(np.int16)
