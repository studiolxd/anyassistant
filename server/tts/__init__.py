"""Text-to-speech plugins.

A plugin is a module of this package with a class registered like this:

    @register("name")
    class MyVoice(Voice):
        def synthesize(self, text): ...   # → int16 mono at 48 kHz

synthesize() is called from a separate thread, sentence by sentence. The default
voice comes from the active locale (tts_voice).

An engine lists its voices without loading (voices(language), as the settings name them:
«ef_dora», «Mónica») and how each is called (label: «Dora»): the LLM's set_voice and the
settings' list use the engine in use's (voices(), find()).
"""

import re
import subprocess
import sys
import unicodedata

import numpy as np

import i18n
import settings
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

    @classmethod
    def voices(cls, language: str) -> list[str]:
        """Its voices in a language (es, en…), as the settings name them; without loading it.
        None listed: it can't tell."""
        return []

    @classmethod
    def label(cls, name: str) -> str:
        """How a voice is called («Dora» for ef_dora): what the user says."""
        return name


def engine(name: str | None = None):
    """The class of an engine (the one in use: settings «tts»), or None (none, or off)."""
    name = name or settings.get("tts")
    return _registry.get(name) if name and name != "none" else None


def voices(language: str | None = None, name: str | None = None) -> list[str]:
    """The voices of the engine in use (or another) in a language (the active one)."""
    found = engine(name)
    return found.voices(language or i18n.L.code) if found else []


def _plain(text: str) -> str:
    """«Mónica», «monica», «ef_dora» → comparable: lowercase, no accents nor separators."""
    text = unicodedata.normalize("NFKD", text.casefold())
    return re.sub(r"[\W_]+", "", "".join(c for c in text if not unicodedata.combining(c)))


def find(said: str, language: str | None = None, name: str | None = None) -> str | None:
    """The voice someone means («Dora», «dora», «ef_dora», «Mónica (Español (España))»), as the
    settings name it, or None."""
    found, wanted = engine(name), _plain(said.split(" (")[0])
    if not found or not wanted:
        return None
    for voice in found.voices(language or i18n.L.code):
        if wanted in (_plain(voice), _plain(found.label(voice))):
            return voice
    return None


def say_voices(language: str) -> list[str]:
    """The Mac's voices in a language (`say -v ?`), by name («Mónica», «Eddy»: the language
    tells which); none elsewhere."""
    if sys.platform != "darwin":
        return []
    output = subprocess.run(["say", "-v", "?"], capture_output=True, text=True).stdout
    found = []
    for line in output.splitlines():
        match = re.match(r"(.+?)\s+([a-z]{2,3})_[A-Z]{2}\s+#", line)
        if match and match.group(2) == language:
            name = match.group(1).strip().split(" (")[0]  # «Eddy (Español (España))» → «Eddy»
            if name not in found:
                found.append(name)
    return found
