"""Calendar notices: «Dentro de 10 minutos: reunión con Ana.», a while before each event of
your Google Calendar (calendar_notice_minutes), said through the plugin «notices» (not at
night, not over anyone, where it says). All-day events and the ones you declined, no.

It reads the calendar (the plugin «google»: bin/gog) every CHECK seconds, and looks every
few seconds whether one is due; each event is told once (moved, it's told again).
"""

import asyncio
import logging
import time

import i18n
import kernel
import options
import settings
import web
from options import Option
from plugins.skills_language import spoken_duration

log = logging.getLogger("calendar")
CHECK = 300  # seconds between readings of the calendar
STEP = 15  # seconds between looks at whether one is due

options.add(Option("calendar_notice_minutes", 10, "how many minutes before an event it gives notice", "assistant",
                   "int", live=True))

_told: set = set()  # (id, start) of the events already told


def sentence(event, now: float) -> str:
    title = event.title or i18n.L("speech.calendar_untitled")
    minutes = round((event.start - now) / 60)
    if minutes < 1:
        return i18n.L("speech.calendar_now", title=title)
    return i18n.L("speech.calendar_soon", duration=spoken_duration(minutes * 60), title=title)


def due(events: list, now: float) -> list:
    """The events to tell now (not told yet): starting within calendar_notice_minutes, or just now."""
    ahead = (settings.get("calendar_notice_minutes") or 10) * 60
    found = [e for e in events if not e.all_day and -60 <= e.start - now <= ahead and (e.id, e.start) not in _told]
    for event in found:
        _told.add((event.id, event.start))
    return found


@web.startup
async def watch(app):
    async def loop():
        events, read = [], 0.0
        while True:
            try:
                if kernel.enabled("calendar-notices") and (google := kernel.module("google")):
                    now = time.time()
                    if now - read > CHECK:
                        read = now
                        found = await asyncio.get_running_loop().run_in_executor(None, google.events, 0, 2)
                        events = found if found is not None else events
                    notices = kernel.module("notices")
                    for event in due(events, now):
                        if notices:
                            asyncio.ensure_future(notices.tell(sentence(event, time.time())))
            except Exception as e:
                log.warning("calendar: %r", e)
            await asyncio.sleep(STEP)

    app["calendar-notices"] = asyncio.ensure_future(loop())
