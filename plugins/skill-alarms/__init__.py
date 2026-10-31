"""Timers, alarms and reminders: «pon un temporizador de 10 minutos», «despiértame
mañana a las 7», «recuérdame en 20 minutos que saque la ropa», «¿cuánto queda?»,
«¿qué alarmas tengo?», «cancela las alarmas». Kept in timers.py; they ring on the
device (plugins/brain-assistant) or on the Mac.

With several devices: on every one (option «alarm_rings»: everywhere), or where it was set
(where_set); «… en todos», «… en la cocina» for one of them (a room or a device's name,
from the plugin «devices»). If that device isn't connected, on every one; stopped on one,
it stops on all.
"""

import asyncio
import logging
import time
from pathlib import Path

import hub
import i18n
import kernel
import options
import settings
import web
import audio
from skills import Skill, skill
from plugins.skills_language import spoken_duration, spoken_list, spoken_when
from plugins.skills_language.parse import Clock, Token, clock, day_tokens, duration, resolve, tokens, words

from . import timers
from options import Option
from tools import ToolError, tool

log = logging.getLogger("skills")
options.add(Option("ring_seconds", 60, "how long an alarm rings if nobody stops it, in seconds; 0: until someone "
                   "stops it (at most 30 minutes)", "skills", "int", live=True))
options.add(Option("snooze_minutes", 5, "«snooze» without saying how long", "skills", "int", live=True))
options.add(Option("alarm_rings", "everywhere", "where timers, alarms and reminders ring: everywhere (every device) "
                   "or where_set (the device they were set on)", "skills", "choice", ["everywhere", "where_set"],
                   live=True))
ALARM = Path(__file__).parent / "sounds" / "alarm.wav"  # three quick high notes


def alarm_sound(skin: str | None):
    """What rings, as 48 kHz PCM: the skin's alarm.wav, or this plugin's."""
    page = kernel.module("page")
    own = page.skins.sound(skin, "alarm") if page and skin else None
    return own if own is not None else audio.wav(ALARM)


def _here() -> str | None:
    """The device it is being set on: the one you're talking to."""
    session = hub.current()
    return session.device if session else None


def _where(where: str, said: str = "") -> str:
    """«It'll ring everywhere.», «It'll ring in the kitchen.» after the confirmation, if asked
    (`said`: your words for it, «la cocina»)."""
    if not where:
        return ""
    return " " + (i18n.L("speech.where_all") if where == "all" else i18n.L("speech.where_room", where=said or where))


def set_timer(seconds: float, label: str = "", where: str = "", said: str = "") -> str:
    timers.add("timer", time.time() + seconds, label, _here(), where)
    return i18n.L("speech.timer_set", duration=spoken_duration(seconds)) + _where(where, said)


def set_alarm(at: float, label: str = "", where: str = "", said: str = "") -> str:
    timers.add("alarm", at, label, _here(), where)
    return i18n.L("speech.alarm_set", when=spoken_when(at)) + _where(where, said)


def set_reminder(at: float, text: str, where: str = "", said: str = "") -> str:
    timers.add("reminder", at, text, _here(), where)
    return i18n.L("speech.reminder_set", when=spoken_when(at), text=text) + _where(where, said)


# --- Where it rings ---

def _names() -> dict[tuple, str]:
    """The rooms and names of the devices (the plugin «devices»), as words to find in a sentence."""
    devices = kernel.module("devices")
    found = {}
    for device in (devices.load().values() if devices else ()):
        for name in (device.get("room"), device.get("name")):
            if name:
                found[tuple(t.plain for t in tokens(name))] = name
    return found


def place(toks: list[Token]) -> tuple[str, set[int]]:
    """Where it was asked to ring, and the words that say it: «en todos (los dispositivos)», «en toda
    la casa», «everywhere» → "all"; «en la cocina» (a room or a device's name) → "cocina"."""
    articles, every, places = words("articles"), words("everywhere"), words("places")
    for i, token in enumerate(toks):
        if token.plain in words("everywhere_alone"):
            return "all", {i}
        if token.plain not in words("where_in"):
            continue
        j = i + 1
        while j < len(toks) and toks[j].plain in articles:
            j += 1
        if j < len(toks) and toks[j].plain in every:
            end = j + 1
            while end < len(toks) and toks[end].plain in articles | places:
                end += 1
            return "all", set(range(i, end))
        for name, kept in sorted(_names().items(), key=lambda n: -len(n[0])):
            if name and tuple(t.plain for t in toks[j:j + len(name)]) == name:
                return kept, set(range(i, j + len(name)))
    return "", set()


def _is(device: str | None, where: str) -> bool:
    """Whether that device is the room or the name «where» (the plugin «devices»)."""
    devices = kernel.module("devices")
    return bool(devices and devices.matches(device, where))


def targets(item: dict) -> list:
    """The connected devices it rings on: where it was asked, else every one (alarm_rings everywhere)
    or where it was set (where_set); if that one isn't connected, every one."""
    sessions = [s for s in hub.all() if s.pc.connectionState == "connected" and hasattr(s.brain, "ring")]
    where = item.get("where") or ("" if settings.get("alarm_rings", "everywhere") == "where_set" else "all")
    if where == "all":
        return sessions
    if where:
        found = [s for s in sessions if _is(s.device, where)]
    else:
        found = [s for s in sessions if s.device and s.device == item.get("device")]
    return found or sessions


def remaining() -> str:
    running = timers.pending("timer")
    if not running:
        return i18n.L("speech.no_timers")
    return i18n.L("speech.remaining", duration=spoken_duration(running[0]["at"] - time.time()))


def listing() -> str:
    items = timers.pending()
    if not items:
        return i18n.L("speech.no_timers")
    parts = []
    for item in items:
        if item["kind"] == "timer":
            parts.append(i18n.L("speech.item_timer", duration=spoken_duration(item["at"] - time.time())))
        elif item["kind"] == "alarm":
            parts.append(i18n.L("speech.item_alarm", when=spoken_when(item["at"])))
        else:
            parts.append(i18n.L("speech.item_reminder", when=spoken_when(item["at"]), text=item["label"]))
    return i18n.L("speech.listing", items=spoken_list(parts))


def cancel(kind: str | None = None) -> str:
    return i18n.L("speech.cancelled" if timers.cancel(kind) else "speech.nothing_to_cancel")


def ring_sentence(item: dict) -> str:
    """What it says when a timer, alarm or reminder rings."""
    if item["kind"] == "timer":
        return i18n.L("speech.timer_done")
    if item["kind"] == "alarm":
        return i18n.L("speech.alarm_ring", time=i18n.L.time_spoken())
    return i18n.L("speech.reminder_ring", text=item.get("label", ""))


async def ring_on_mac(item: dict):
    """No device connected: it rings on the Mac (afplay and say)."""
    log.info("ringing on the Mac: %s", item["kind"])
    for _ in range(3):
        await (await asyncio.create_subprocess_exec("afplay", str(ALARM))).wait()
    await (await asyncio.create_subprocess_exec("say", "-v", i18n.L.tts_voice, ring_sentence(item))).wait()


def label(toks: list[Token], span, when, skip: set[int] = frozenset()) -> str:
    """What to remind: the words that aren't the command, the time, the day or where it rings."""
    used = set(day_tokens(toks)) | set(skip)
    for found in (span, when):
        if found:
            used |= set(range(found.start, found.end))
            if found.start and toks[found.start - 1].plain in words("in"):
                used.add(found.start - 1)
    verbs = [i for i, t in enumerate(toks) if t.plain in words("reminder")]
    used |= set(verbs)
    after = verbs[0] if verbs else -1  # «Quiero que me recuerdes…»: what comes before isn't it
    if verbs and toks[verbs[0]].plain in words("notify"):
        # «avísame en 10 minutos (de) que apague el horno»: only what follows «que» is a reminder;
        # «avísame dentro de un rato largo, como 45 minutos» is just a timer.
        joined = [i for i, t in enumerate(toks) if i > after and t.plain in words("connectors")]
        if not joined:
            return ""
        after = joined[0]
    rest = [t for i, t in enumerate(toks) if i not in used and i > after]
    edges = {"que", "de", "a", "to", "that", "me", "about", "para", "en", "in", "at", "y", "and", "dentro"}
    while rest and rest[0].plain in edges:
        rest.pop(0)
    while rest and rest[-1].plain in edges:
        rest.pop()
    return " ".join(t.word for t in rest)


@skill
class Alarms(Skill):
    order = 31

    def answer(self, text, toks):
        said = {t.plain for t in toks}
        kind = next((k for k in timers.KINDS if said & words(k)), None)
        when = clock(toks)
        span = duration(toks)
        where, at_where = place(toks) if kind else ("", set())
        heard = " ".join(toks[i].word for i in sorted(at_where)[1:])  # «la cocina», without its «en»
        if kind and said & words("cancel"):
            return cancel(None if said & words("all") else kind)
        if said & words("remaining") and (kind == "timer" or said & words("math")) and not span:
            return remaining()
        if kind and said & words("list") and not span and not when:
            return listing()
        if kind == "reminder" and (span or when):
            at = time.time() + span.value if span and not when else resolve(when.value)
            what = label(toks, span, when, at_where)
            return (set_reminder(at, what, where, heard) if what
                    else set_timer(span.value, where=where, said=heard) if span else None)
        if kind == "alarm" and when:
            return set_alarm(resolve(when.value, waking=True), where=where, said=heard)
        if kind in ("timer", "alarm") and span:
            return (set_timer(span.value, where=where, said=heard) if kind == "timer"
                    else set_alarm(time.time() + span.value, where=where, said=heard))
        return None


# --- As tools, for the LLM, when asked in its own words ---

def next_time(hour: int, minute: int) -> float:
    """The next time the clock shows hour:minute (24 h)."""
    now = time.localtime()
    at = time.mktime((now.tm_year, now.tm_mon, now.tm_mday, hour, minute, 0, 0, 0, -1))
    return at if at > time.time() else at + 86400


def _at(hour, minute, day, seconds) -> float:
    if seconds:
        return time.time() + seconds
    if hour is None:
        raise ToolError("give seconds from now, or hour and minute")
    if day is None:
        return next_time(int(hour) % 24, int(minute or 0))
    return resolve(Clock(int(hour) % 24, int(minute or 0), None, int(day)), waking=True)


WHERE = (" where: «all» rings on every device, a room or a device's name (get_devices) rings there; "
         "empty, on this device.")


@tool("A timer: seconds from now, optionally with a label." + WHERE, name="set_timer")
def timer_tool(seconds: float, label: str = "", where: str = "") -> str:
    if not 1 <= seconds <= 7 * 86400:
        raise ToolError("seconds: from 1 to a week")
    return set_timer(seconds, label, where.strip())


@tool("An alarm at hour:minute (24 h; day 0 today, 1 tomorrow, 2 the day after; without day, the next time it "
      "comes), or in some seconds." + WHERE, name="set_alarm")
def alarm_tool(hour: int | None = None, minute: int = 0, day: int | None = None, seconds: float = 0,
               where: str = "") -> str:
    return set_alarm(_at(hour, minute, day, seconds), where=where.strip())


@tool("A reminder that says text aloud at hour:minute (24 h; day as for alarms) or in some seconds (a message "
      "to another device now isn't one: tell_device)." + WHERE,
      name="set_reminder")
def reminder_tool(text: str, hour: int | None = None, minute: int = 0, day: int | None = None,
                  seconds: float = 0, where: str = "") -> str:
    if not text.strip():
        raise ToolError("what should it remind?")
    return set_reminder(_at(hour, minute, day, seconds), text.strip(), where.strip())


@tool("The running timers, alarms and reminders.")
def list_timers() -> str:
    return listing()


@tool("Cancel the timers, alarms or reminders (kind), or all of them.",
      choices={"kind": ["timer", "alarm", "reminder", "all"]})
def cancel_timers(kind: str = "all") -> str:
    return cancel(kind if kind in timers.KINDS else None)


@web.startup
async def ring_when_due(app):
    """Timers, alarms and reminders: on the devices (targets), or on the Mac if none is connected."""
    async def loop():
        while True:
            try:
                if kernel.enabled("skill-alarms"):
                    for item in timers.due():
                        found = targets(item)
                        log.info("ringing %s on %d device(s)", item["kind"], len(found))
                        for session in found:  # the same item: stopped on one, it stops on all
                            asyncio.ensure_future(session.brain.ring(item))
                        if not found:
                            asyncio.ensure_future(ring_on_mac(item))
            except Exception as e:
                log.warning("timers: %r", e)
            await asyncio.sleep(0.5)

    app["timers"] = asyncio.ensure_future(loop())
