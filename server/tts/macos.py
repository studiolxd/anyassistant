"""Las voces de macOS con `say` (Mónica, Eddy, Reed…: `say -v '?' | grep es_`)."""

import subprocess
import tempfile
import wave
from pathlib import Path

import numpy as np

from tts import TASA, Voz, registrar


@registrar("macos")
class MacOS(Voz):
    def __init__(self, voz=None, velocidad=None):
        super().__init__(voz or "Mónica", velocidad)

    def sintetizar(self, texto: str) -> np.ndarray:
        with tempfile.TemporaryDirectory() as carpeta:
            salida = Path(carpeta) / "voz.wav"
            orden = ["say", "-v", self.voz, "-o", str(salida),
                     "--file-format=WAVE", f"--data-format=LEI16@{TASA}"]
            if self.velocidad:
                orden += ["-r", str(self.velocidad)]  # palabras por minuto
            subprocess.run(orden + ["--", texto], check=True)
            with wave.open(str(salida)) as w:
                return np.frombuffer(w.readframes(w.getnframes()), dtype=np.int16)
