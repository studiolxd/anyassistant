"""Whisper on the Apple Silicon GPU with MLX."""

import sys

import numpy as np

import models
from stt import GPU, Transcriber, register

_models = {}


def transcribe_mlx(audio: np.ndarray, model: str, language: str, prompt: str | None = None) -> str:
    """Transcribes with any MLX Whisper model, keeping all of them loaded.

    mlx_whisper keeps a single model and reloads when asked for another; here two
    are used at once (the STT one and the small wake-word one). The GPU lock stops
    two threads from using it at the same time.
    """
    import mlx_whisper

    holder = sys.modules["mlx_whisper.transcribe"].ModelHolder
    if not getattr(holder, "_many", False):
        from mlx_whisper.load_models import load_model

        def get_model(cls, path, dtype):
            if path not in _models:
                _models[path] = load_model(path, dtype=dtype)
            return _models[path]

        holder.get_model = classmethod(get_model)
        holder._many = True

    with GPU:
        result = mlx_whisper.transcribe(
            audio,
            path_or_hf_repo=models.pinned(model),
            language=language,
            # Standalone sentences: without previous context it makes up less.
            condition_on_previous_text=False,
            initial_prompt=prompt,
        )
    return result["text"].strip()


@register("mlx-whisper")
class MlxWhisper(Transcriber):
    def __init__(self, language="en", model=None):
        super().__init__(language, model or "mlx-community/whisper-large-v3-turbo")

    def transcribe(self, audio: np.ndarray) -> str:
        return transcribe_mlx(audio, self.model, self.language)
