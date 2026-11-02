"""Sounds: two short notes when it wakes up (rising) and when it falls asleep (falling).

A theme's own sounds/wake.wav and sleep.wav win; otherwise these (sounds/ here). With
the plugin off, it wakes and sleeps in silence. Replace it with one of yours (same
id, your folder) to have other sounds everywhere.
"""

from pathlib import Path

import audio
import kernel

HERE = Path(__file__).parent / "sounds"


def sound(kind: str, theme: str | None):
    """«wake» or «sleep» as 48 kHz PCM: the theme's, or this plugin's."""
    page = kernel.module("page")
    own = page.themes.sound(theme, kind) if page and theme else None
    return own if own is not None else audio.wav(HERE / f"{kind}.wav")
