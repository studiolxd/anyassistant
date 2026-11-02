"""Sounds: two short notes when it wakes up (rising) and when it falls asleep (falling).

A theme's own sounds/wake.wav and sleep.wav win; otherwise these (sounds/ here). With
the plugin off, it wakes and sleeps in silence. Replace it with one of yours (same
id, your folder) to have other sounds everywhere.
"""

from pathlib import Path

from aiohttp import web as http

import audio
import kernel
import settings
import web

HERE = Path(__file__).parent / "sounds"


def sound(kind: str, theme: str | None):
    """«wake» or «sleep» as 48 kHz PCM: the theme's, or this plugin's."""
    page = kernel.module("page")
    own = page.themes.sound(theme, kind) if page and theme else None
    return own if own is not None else audio.wav(HERE / f"{kind}.wav")


@web.route("GET", "/sounds/{kind}.wav")
async def _sound(request):
    """What a theme sounds like (wake, sleep, alarm), as it plays: its own, or the system's. For
    the themes page («Sonidos»); X-Theme-Sound: 1 if it is the theme's own."""
    kind = request.match_info["kind"]
    page = kernel.module("page")
    chosen = request.query.get("theme", "")
    theme = chosen if page and chosen in page.themes.available() else settings.get("theme")
    if kind in ("wake", "sleep"):
        pcm = sound(kind, theme)
    elif kind == "alarm" and kernel.module("skill-alarms"):
        pcm = kernel.module("skill-alarms").alarm_sound(theme)
    else:
        return http.Response(status=404)
    if pcm is None:
        return http.Response(status=404)
    own = page is not None and page.themes.sound(theme, kind) is not None
    return http.Response(body=audio.wav_bytes(pcm), content_type="audio/wav",
                         headers={"X-Theme-Sound": "1" if own else "0"})
