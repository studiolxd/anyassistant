"""Speech-to-text plugins.

A plugin is a module of this package with a class registered like this:

    @register("name")
    class MyEngine(Transcriber):
        def transcribe(self, audio): ...

One that can leave memory while nobody talks (settings «stt_unload_minutes», Unloading) also
has load() and unload(): its model goes and comes back; the engine object stays.
"""

import logging
import threading
import time

import numpy as np

import settings
from registry import Registry

log = logging.getLogger("stt")

RATE = 16000  # every plugin receives float32 mono at 16 kHz

# The MLX plugins (and the Whisper wake word) share the GPU: one at a time.
GPU = threading.Lock()

_registry = Registry("stt", "STT")
register = _registry.register
create = _registry.create
available = _registry.available

UNLOAD_MINUTES = 5  # settings «stt_unload_minutes»: 0 never
CHECK_SECONDS = 15  # how often Unloading looks at the clock


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

    def load(self):
        """Its model in memory again after unload(); an engine without unload keeps it always."""

    def unload(self) -> bool:
        """Frees its model's memory (load() brings it back). False: this engine can't."""
        return False


class Unloading(Transcriber):
    """An engine whose model leaves memory after «stt_unload_minutes» without transcribing (0:
    never) and comes back the next time it is needed, with that sentence waiting for it.

    busy() says whether a conversation is going on (then it stays loaded). prepare() starts
    loading in the background: the Ear calls it when a device wakes up, so the model is back
    (or nearly) by the time the first sentence ends.
    """

    def __init__(self, engine: Transcriber, busy=None, minutes=None):
        super().__init__(engine.language, engine.model)
        self.engine = engine
        self.name = engine.name
        self.busy = busy or (lambda: False)
        self.minutes = minutes or (lambda: settings.get("stt_unload_minutes", UNLOAD_MINUTES))
        self.loaded = True  # the engine loads when it is created
        self.last_used = time.time()
        self._lock = threading.Lock()  # one thing at a time: loading, unloading, transcribing
        self._preparing = None
        self._stop = threading.Event()
        threading.Thread(target=self._watch, name="stt-unload", daemon=True).start()

    def warm_up(self):
        with self._lock:
            self._ensure()
            self.engine.warm_up()
            self.last_used = time.time()

    def transcribe(self, audio: np.ndarray) -> str:
        with self._lock:
            self._ensure()
            self.last_used = time.time()
            try:
                return self.engine.transcribe(audio)
            finally:
                self.last_used = time.time()

    def prepare(self):
        """Starts loading the model, if it isn't, without waiting for it."""
        if self.loaded or (self._preparing and self._preparing.is_alive()):
            return
        self.last_used = time.time()  # it is wanted: not to be unloaded again at once

        def load():
            with self._lock:
                self._ensure()

        self._preparing = threading.Thread(target=load, name="stt-load", daemon=True)
        self._preparing.start()

    def check(self, now: float | None = None) -> bool:
        """Unloads the model if it has been idle long enough and no conversation is going on."""
        minutes = self.minutes()
        if not minutes or not self.loaded or self.busy():
            return False
        if (now or time.time()) - self.last_used < minutes * 60:
            return False
        with self._lock:
            if not self.loaded or self.busy():
                return False
            if not self.engine.unload():
                log.info("STT %s can't be unloaded: it stays in memory", self.name)
                self.minutes = lambda: 0  # not to be tried every time
                return False
            self.loaded = False
            log.info("STT %s unloaded: %g min without use", self.name, minutes)
            return True

    def close(self):
        self._stop.set()

    def _ensure(self):
        """With the lock: the model in memory, warmed up so the sentence doesn't pay for it twice."""
        if self.loaded:
            return
        start = time.time()
        self.engine.load()
        self.engine.warm_up()
        self.loaded = True
        self.last_used = time.time()
        log.info("STT %s loaded again in %.1f s", self.name, time.time() - start)

    def _watch(self):
        while not self._stop.wait(CHECK_SECONDS):
            try:
                self.check()
            except Exception as e:  # noqa: BLE001 (it must keep watching)
                log.warning("STT %s couldn't be unloaded: %r", self.name, e)
