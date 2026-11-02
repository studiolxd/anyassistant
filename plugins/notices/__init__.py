"""Notices: what it says on its own (the plugin calendar-notices…), politely.

- Not at night: during «quiet_hours» (23:00-08:00) a notice isn't said (alarms, which you
  set yourself, ring anyway).
- Not over anyone: while a device is in a conversation, hearing someone, thinking or
  speaking, it waits (up to WAIT seconds; then it says it anyway, or it would be late).
- Where: every connected device («notices_where»: everywhere), or the last one you talked
  to (last). A soft tone first (the theme's «wake» sound), then the sentence, on screen too.
- Not lost: each notice is also kept for the devices that weren't connected (an hour; a
  message for one device, «dile al reloj…», 12 hours). A device gets those it missed when it
  connects ({"type": "notice", "text"}: the phone shows a notification); the watch, which
  never stays connected, asks for them (GET /notices, and with each answer of /talk) and
  shows them on the wrist. Each device gets each one once.

    notices = kernel.module("notices")
    await notices.tell("In 10 minutes: dentist.")
"""

import asyncio
import json
import logging
import time

from aiohttp import web as http

import events
import hub
import options
import paths
import settings
import web
from options import Option

log = logging.getLogger("notices")
WAIT = 90  # seconds it waits for a quiet moment at most
FILE = paths.HOME / "notices.json"  # those kept for the devices that missed them
LASTS = 3600  # seconds a notice is kept for those that missed it
LASTS_FOR_ONE = 12 * 3600  # a message for one device («dile al reloj…»)

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
    for session in found:
        if hasattr(session.brain, "_beep"):
            session.brain._beep("wake")  # a soft tone first: it's about to say something
        session.brain.say(text)
    keep(text, told={s.device for s in found if s.device})  # for those that weren't connected
    if not found:
        log.info("no device: kept «%s» for when one connects", settings.private(text))
        return False
    log.info("notice on %d device(s): «%s»", len(found), settings.private(text))
    return True


# --- Kept for those that missed them ---

def _load() -> list[dict]:
    try:
        return json.loads(FILE.read_text())
    except (OSError, ValueError):
        return []


def _save(kept: list[dict]):
    FILE.parent.mkdir(parents=True, exist_ok=True)
    FILE.write_text(json.dumps(kept, ensure_ascii=False, indent=2) + "\n")


def _alive(item: dict, now: float) -> bool:
    return now - item["at"] < (LASTS_FOR_ONE if item.get("for") else LASTS)


def keep(text: str, device: str | None = None, told: set | None = None):
    """Keeps a notice for the devices that didn't get it: every one but `told`, or only `device`."""
    now = time.time()
    kept = [i for i in _load() if _alive(i, now)]
    kept.append({"text": text, "at": now, "for": device, "told": sorted(told or ())})
    _save(kept)


def missed(device: str) -> list[str]:
    """What this device missed (oldest first), now told: it won't get them again."""
    now = time.time()
    kept = [i for i in _load() if _alive(i, now)]
    found = []
    for item in kept:
        if device not in item["told"] and item.get("for") in (None, device):
            found.append(item["text"])
            item["told"].append(device)
    if found:
        log.info("%d missed notice(s) for %s", len(found), device)
    _save([i for i in kept if not (i.get("for") and i["for"] in i["told"])])  # one device's, once told: gone
    return found


@events.on("connected")
async def _catch_up(session):
    """A device that connects gets what it missed, once it can be sent to (not the watch: it asks)."""
    if getattr(session, "press_to_talk", False) or not session.device:
        return
    for _ in range(40):  # its channel opens a moment after it connects
        if session.pc.connectionState == "connected":
            break
        await asyncio.sleep(0.5)
    else:
        return
    await asyncio.sleep(1)
    for text in missed(session.device):
        session.send({"type": "notice", "text": text})


@web.route("GET", "/notices")
async def _missed(request):
    """What the device (?device=) missed: the watch asks when it opens and now and then."""
    if refusal := web.refused(request):  # pairing, as for /talk
        return refusal
    device = request.query.get("device", "")
    if not device or len(device) > 64:
        return http.json_response({"error": "?device=<its id>"}, status=400)
    return http.json_response({"notices": missed(device)})
