"""Las voces de macOS con AVSpeechSynthesizer, que se queda cargado (~50 ms por frase).

Mismas voces que `say` (Mónica, Eddy, Reed…). Si en Ajustes → Accesibilidad →
Contenido leído se descarga la versión mejorada de una voz, la usa.
Habla con avspeech_puente.swift, que se compila la primera vez en .build/.
"""

import base64
import json
import subprocess
import threading
from pathlib import Path

import numpy as np
from scipy.signal import resample_poly

from swift import compilar
from tts import TASA, Voz, registrar


@registrar("avspeech")
class AVSpeech(Voz):
    def __init__(self, voz=None, velocidad=None):
        super().__init__(voz or "Mónica", velocidad)
        binario = compilar(Path(__file__).with_name("avspeech_puente.swift"), "avspeech-puente")
        self._proceso = subprocess.Popen(
            [str(binario)], stdin=subprocess.PIPE, stdout=subprocess.PIPE, text=True
        )
        self._turno = threading.Lock()  # sintetizar() se llama desde hilos

    def sintetizar(self, texto: str) -> np.ndarray:
        orden = {"texto": texto, "voz": self.voz}
        if self.velocidad:
            orden["velocidad"] = self.velocidad
        with self._turno:
            self._proceso.stdin.write(json.dumps(orden) + "\n")
            self._proceso.stdin.flush()
            respuesta = json.loads(self._proceso.stdout.readline())
        if "error" in respuesta:
            raise RuntimeError(respuesta["error"])
        audio = np.frombuffer(base64.b64decode(respuesta["audio"]), dtype=np.float32)
        tasa = round(respuesta["tasa"])
        if tasa != TASA:
            mcd = np.gcd(tasa, TASA)
            audio = resample_poly(audio, TASA // mcd, tasa // mcd)
        return (np.clip(audio, -1, 1) * 32767).astype(np.int16)

    def cerrar(self):
        self._proceso.kill()
