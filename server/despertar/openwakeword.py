"""openWakeWord: modelos ONNX pequeños que corren en la CPU del Mac.

--palabra acepta un modelo de serie (hey_jarvis, alexa, hey_mycroft…) o la
ruta a un .onnx propio entrenado con openWakeWord.
"""

import logging
from pathlib import Path

import numpy as np

from despertar import Despertador, registrar

log = logging.getLogger("despertar")

TROZO = 1280  # 80 ms a 16 kHz, lo que espera el modelo


@registrar("openwakeword")
class OpenWakeWord(Despertador):
    # Su historial de audio tiene que avanzar siempre, o al dormirse volvería
    # a oír la palabra vieja y se despertaría solo.
    continuo = True

    def __init__(self, palabra=None, umbral=0.5):
        super().__init__(palabra or "hey_jarvis", umbral)
        import openwakeword
        from openwakeword.model import Model

        if Path(self.palabra).suffix == ".onnx":
            ruta = self.palabra
        elif self.palabra in openwakeword.models:
            ruta = openwakeword.models[self.palabra]["model_path"]
        else:
            raise ValueError(
                f"Palabra desconocida: {self.palabra}. Hay: {', '.join(openwakeword.models)}"
            )
        self.frase = Path(ruta).stem.split("_v")[0].replace("_", " ").capitalize()
        self.modelo = Model(wakeword_model_paths=[ruta])
        self.pendiente = np.zeros(0, dtype=np.int16)

    def escuchar(self, audio: np.ndarray) -> bool:
        pcm = (np.clip(audio, -1, 1) * 32767).astype(np.int16)
        self.pendiente = np.concatenate([self.pendiente, pcm])
        detectado = False
        while len(self.pendiente) >= TROZO:
            trozo, self.pendiente = self.pendiente[:TROZO], self.pendiente[TROZO:]
            puntuacion = max(self.modelo.predict(trozo).values())
            if puntuacion >= self.umbral:
                detectado = True
            self._casi(puntuacion)
        return detectado

    def _casi(self, puntuacion: float):
        """Apunta el pico de cada intento: ayuda a ajustar --umbral."""
        if puntuacion >= 0.05:
            self.pico = max(getattr(self, "pico", 0.0), puntuacion)
        elif getattr(self, "pico", 0.0):
            log.info("intento: %.2f (umbral %.2f)", self.pico, self.umbral)
            self.pico = 0.0

    def reiniciar(self):
        self.modelo.reset()
        self.pendiente = np.zeros(0, dtype=np.int16)
