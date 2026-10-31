"""Voice activity detection plugins: is there speech in this bit of audio?

A plugin is a module of this package with a class registered like this:

    @register("name")
    class MyVAD(VAD):
        def probability(self, window): ...   # float32 mono 16 kHz, WINDOW samples → 0–1
        def reset(self): ...                 # a new stream: forget what it heard

The ear (brain/ear.py) and the whisper wake word cut sentences with it. Chosen with
settings «vad»; each listener gets its own instance (they keep state).
"""

import numpy as np

import settings
from plugins import Registry

RATE = 16000
WINDOW = 512  # samples (32 ms)

_registry = Registry(__name__, __path__, "VAD")
register = _registry.register
available = _registry.available


class VAD:
    name = "?"

    def probability(self, window: np.ndarray) -> float:
        raise NotImplementedError

    def reset(self):
        pass


def create() -> VAD:
    return _registry.create(settings.get("vad") or "silero")
