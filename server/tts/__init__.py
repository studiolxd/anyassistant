"""Text-to-speech plugins.

A plugin is a module of this package with a class registered like this:

    @register("name")
    class MyVoice(Voice):
        def synthesize(self, text): ...   # → int16 mono at 48 kHz

synthesize() is called from a separate thread, sentence by sentence. The default
voice comes from the active locale (tts_voice).
"""

import numpy as np

import i18n
from registry import Registry

RATE = 48000  # what the Speaker expects

_registry = Registry("tts", "TTS")
register = _registry.register
create = _registry.create
available = _registry.available


class Voice:
    name = "?"

    def __init__(self, voice: str | None = None, rate: int | None = None):
        self.voice = voice or i18n.L.tts_voice
        self.rate = rate  # words per minute

    def warm_up(self):
        self.synthesize(i18n.L("speech.warm_up"))

    def synthesize(self, text: str) -> np.ndarray:
        raise NotImplementedError

    def close(self):
        """When the server stops: releases processes."""
