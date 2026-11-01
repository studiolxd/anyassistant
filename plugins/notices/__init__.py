"""Notices: what it says on its own (the plugin calendar-notices…), politely.

- Not at night: during «quiet_hours» (23:00-08:00) a notice isn't said (alarms, which you
  set yourself, ring anyway).
- Not over anyone: while a device is in a conversation, hearing someone, thinking or
  speaking, it waits (up to WAIT seconds; then it says it anyway, or it would be late).
- Where: every connected device («notices_where»: everywhere), or the last one you talked
  to (last). A soft tone first (the skin's «wake» sound), then the sentence, on screen too.

    notices = kernel.module("notices")
    await notices.tell("In 10 minutes: dentist.")
"""

import asyncio
import logging
import time

import hub
import options
import settings
from options import Option

log = logging.getLogger("notices")
WAIT = 90  # seconds it waits for a quiet moment at most

options.add(Option("quiet_hours", "23:00-08:00", "hours when it doesn't give notices (e.g. 23:00-08:00; empty: any "
                   "time); alarms ring anyway", "assistant", live=True))
options.add(Option("notices_where", "everywhere", "where notices are said: on every device, or on the last one you "
                   "talked to", "assistant", "choice", ["everywhere", "last"], live=True))


def _minutes(clock: str) -> int:
    hours, minutes = clock.strip().split(":")
    return int(hours) * 60 + int(minutes)


def quiet(now: float | None = None) -> bool:
    """Whether it is within quiet_hours (they may cross midnight: 23:00-08:00)."""
    hours = (settings.get("quiet_hours", "23:00-08:00") or "").strip()
    if not hours:
        return False
    try:
        start, end = (_minutes(part) for part in hours.split("-"))
    except ValueError:
        log.warning("quiet_hours isn't «HH:MM-HH:MM»: %r", hours)
        return False
    t = time.localtime(now)
    minute = t.tm_hour * 60 + t.tm_min
    return start <= minute < end if start <= end else minute >= start or minute < end


def _busy(session) -> bool:
    """In a conversation, hearing someone, thinking, speaking or ringing."""
    brain = session.brain
    ear = getattr(brain, "ear", None)
    turn = getattr(brain, "turn", None)
    return bool((ear and ((ear.wake and ear.awake) or ear.speaking or ear.deaf()))
                or (turn and turn.locked()) or getattr(brain, "ringing", None))


def targets() -> list:
    """The connected devices a notice goes to."""
    found = [s for s in hub.all() if s.pc.connectionState == "connected" and hasattr(s.brain, "say")]
    if settings.get("notices_where", "everywhere") == "last":
        current = hub.connected()
        if current in found:
            return [current]
    return found


async def tell(text: str, wait: float = WAIT) -> bool:
    """Says it on the devices when it is a good moment; False if it wasn't said (night, no device)."""
    if quiet():
        log.info("quiet hours: not said «%s»", settings.private(text))
        return False
    until = time.time() + wait
    while any(_busy(s) for s in targets()) and time.time() < until:
        await asyncio.sleep(1)
    found = targets()
    if not found:
        log.info("no device: not said «%s»", settings.private(text))
        return False
    for session in found:
        if hasattr(session.brain, "_beep"):
            session.brain._beep("wake")  # a soft tone first: it's about to say something
        session.brain.say(text)
    log.info("notice on %d device(s): «%s»", len(found), settings.private(text))
    return True
