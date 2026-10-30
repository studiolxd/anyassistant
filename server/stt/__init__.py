"""Speech-to-text plugins.

A plugin is a module of this package with a class registered like this:

    @register("name")
    class MyEngine(Transcriber):
        def transcribe(self, audio): ...
"""

import threading

import numpy as np

from plugins import Registry

RATE = 16000  # every plugin receives float32 mono at 16 kHz

# The MLX plugins (and the Whisper wake word) share the GPU: one at a time.
GPU = threading.Lock()

_registry = Registry(__name__, __path__, "STT")
register = _registry.register
create = _registry.create
available = _registry.available


class Transcriber:
    name = "?"

    def __init__(self, language: str = "en", model: str | None = None):
        self.language = language
        self.model = model

    def warm_up(self):
        """Loads the model so the first sentence doesn't wait."""
        self.transcribe(np.zeros(RATE // 2, dtype=np.float32))

    def transcribe(self, audio: np.ndarray) -> str:
        raise NotImplementedError
