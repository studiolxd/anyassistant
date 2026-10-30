"""Whisper en la GPU de Apple Silicon con MLX."""

import sys
import threading

import numpy as np

from stt import Transcriptor, registrar

_cerrojo = threading.Lock()
_modelos = {}


def transcribir_mlx(audio: np.ndarray, modelo: str, idioma: str, pista: str | None = None) -> str:
    """Transcribe con cualquier modelo MLX; los deja todos cargados en memoria.

    mlx_whisper solo guarda un modelo y recarga si se le pide otro; aquí se
    usan dos a la vez (el de STT y el pequeño de la palabra de activación).
    El cerrojo evita que dos hilos usen la GPU a la vez.
    """
    import mlx_whisper

    holder = sys.modules["mlx_whisper.transcribe"].ModelHolder
    if not getattr(holder, "_varios", False):
        from mlx_whisper.load_models import load_model

        def get_model(cls, ruta, dtype):
            if ruta not in _modelos:
                _modelos[ruta] = load_model(ruta, dtype=dtype)
            return _modelos[ruta]

        holder.get_model = classmethod(get_model)
        holder._varios = True

    with _cerrojo:
        resultado = mlx_whisper.transcribe(
            audio,
            path_or_hf_repo=modelo,
            language=idioma,
            # Frases sueltas: sin contexto previo se inventa menos.
            condition_on_previous_text=False,
            initial_prompt=pista,
        )
    return resultado["text"].strip()


@registrar("mlx-whisper")
class MlxWhisper(Transcriptor):
    def __init__(self, idioma="es", modelo=None):
        super().__init__(idioma, modelo or "mlx-community/whisper-large-v3-turbo")

    def transcribir(self, audio: np.ndarray) -> str:
        return transcribir_mlx(audio, self.modelo, self.idioma)
