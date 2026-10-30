"""Wake-word plugins.

A plugin is a module of this package with a class registered like this:

    @register("name")
    class MyWakeWord(WakeWord):
        def listen(self, audio): ...   # float32 mono 16 kHz → bool
        def reset(self): ...

It receives audio in chunks of any size and returns True on the chunk where it
recognizes the word. With --wake none everything is heard, without a word.

Optional: if the plugin already heard the whole sentence ("Hey Jarvis, what
time is it?"), it leaves it in self.heard_sentence (float32 16 kHz) and the ear
transcribes it without waiting for another one; and strip(text) removes the
word from the transcribed text.
"""

import numpy as np

from plugins import Registry

RATE = 16000

_registry = Registry(__name__, __path__, "wake word")
register = _registry.register
create = _registry.create
available = _registry.available


class WakeWord:
    name = "?"
    phrase = "?"  # how it is said, to show it on screen
    continuous = False  # True if it also needs to hear while awake

    def __init__(self, word: str | None = None, threshold: float = 0.5):
        self.word = word
        self.threshold = threshold

    def listen(self, audio: np.ndarray) -> bool:
        raise NotImplementedError

    def reset(self):
        pass
