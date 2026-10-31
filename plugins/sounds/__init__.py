"""Sounds: two short notes when it wakes up (rising) and when it falls asleep (falling).

A skin's own sounds/wake.wav and sleep.wav win; otherwise these (sounds/ here). With
the plugin off, it wakes and sleeps in silence. Replace it with one of yours (same
id, your folder) to have other sounds everywhere.
"""

from pathlib import Path

import audio
import kernel

HERE = Path(__file__).parent / "sounds"


def sound(kind: str, skin: str | None):
    """«wake» or «sleep» as 48 kHz PCM: the skin's, or this plugin's."""
    page = kernel.module("page")
    own = page.skins.sound(skin, kind) if page and skin else None
    return own if own is not None else audio.wav(HERE / f"{kind}.wav")
