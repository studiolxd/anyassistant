"""Local skills, without an LLM: time and date, timers, alarms, reminders, sums,
unit conversions and volume (settings «skills», on by default).

quick(text) understands the usual ways of saying them, at once and offline, with
the words of the locale («skills»). If a sentence sounds like one but doesn't fit
(«avísame dentro de un rato largo, como 40 minutos»), interpreter.py may ask
Apple's local model to turn it into data (settings «interpreter»: auto, apple or
off). Each skill is a function with plain arguments, also used by the LLM's tools
(tools.py). They return the sentence to say.
"""

import logging
import time

import i18n
import settings
from skills import timers
from skills.calc import calculate, spoken
from skills.parse import Token, clock, day_tokens, duration, resolve, tokens, vocabulary, words
from skills.units import convert as find_conversion
from skills.units import name as unit_name

log = logging.getLogger("skills")
VOLUME_STEP = 20


def enabled() -> bool:
    return settings.get("skills", True) is not False


# --- How things are said ---

def spoken_duration(seconds: float) -> str:
    names = vocabulary()["duration_names"]
    seconds = round(seconds)
    hours, rest = divmod(seconds, 3600)
    minutes, secs = divmod(rest, 60)
    if hours:
        secs = 0  # «1 hour and 20 minutes», not «… and 7 seconds»
    parts = [f"{n} {names[unit][0 if n == 1 else 1]}"
             for n, unit in ((hours, "hour"), (minutes, "minute"), (secs, "second")) if n]
    if not parts:
        parts = [f"0 {names['second'][1]}"]
    return i18n.L("speech.duration_and").join([", ".join(parts[:-1]), parts[-1]] if len(parts) > 1 else parts)


def spoken_when(at: float) -> str:
    t = time.localtime(at)
    today = time.localtime()
    days = (time.mktime((t.tm_year, t.tm_mon, t.tm_mday, 0, 0, 0, 0, 0, -1))
            - time.mktime((today.tm_year, today.tm_mon, today.tm_mday, 0, 0, 0, 0, 0, -1))) // 86400
    moment = i18n.L.time_spoken(t)
    if days == 0:
        return i18n.L("speech.when_today", time=moment)
    if days == 1:
        return i18n.L("speech.when_tomorrow", time=moment)
    return i18n.L("speech.when_day", date=i18n.L.date_spoken(t), time=moment)


def _list(parts: list[str]) -> str:
    joiner = i18n.L("speech.list_and")
    return parts[0] if len(parts) == 1 else ", ".join(parts[:-1]) + joiner + parts[-1]


# --- The skills ---

def say_time() -> str:
    t = time.localtime()
    one = t.tm_hour % 12 == 1
    return i18n.L("speech.time_is_one" if one else "speech.time_is", time=i18n.L.time_spoken(t))


def say_date() -> str:
    return i18n.L("speech.date_is", date=i18n.L.date_spoken())


def set_timer(seconds: float, label: str = "") -> str:
    timers.add("timer", time.time() + seconds, label)
    return i18n.L("speech.timer_set", duration=spoken_duration(seconds))


def set_alarm(at: float, label: str = "") -> str:
    timers.add("alarm", at, label)
    return i18n.L("speech.alarm_set", when=spoken_when(at))


def set_reminder(at: float, text: str) -> str:
    timers.add("reminder", at, text)
    return i18n.L("speech.reminder_set", when=spoken_when(at), text=text)


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
    return i18n.L("speech.listing", items=_list(parts))


def cancel(kind: str | None = None) -> str:
    return i18n.L("speech.cancelled" if timers.cancel(kind) else "speech.nothing_to_cancel")


def math(a: float, op: str, b: float) -> str:
    result = {"+": a + b, "-": a - b, "*": a * b, "/": a / b if b else float("inf"), "^": a ** b,
              "%": a * b / 100}[op]
    return i18n.L("speech.math", result=spoken(result))


def conversion(value: float, source: str, target: str, result: float) -> str:
    return i18n.L("speech.convert", value=spoken(value), source=unit_name(source, value),
                  result=spoken(result), target=unit_name(target, result))


def set_volume(percent: int) -> str:
    percent = max(5, min(100, int(percent)))
    settings.save(volume=percent)
    settings.refresh()
    return i18n.L("speech.volume", percent=percent)


def ring_sentence(item: dict) -> str:
    """What it says when a timer, alarm or reminder rings."""
    if item["kind"] == "timer":
        return i18n.L("speech.timer_done")
    if item["kind"] == "alarm":
        return i18n.L("speech.alarm_ring", time=i18n.L.time_spoken())
    return i18n.L("speech.reminder_ring", text=item.get("label", ""))


async def ring_on_mac(item: dict):
    """No device connected: it rings on the Mac (afplay and say)."""
    import asyncio
    import wave
    from pathlib import Path

    from audio import RATE, alarm_tone

    path = Path(__file__).resolve().parents[2] / ".build" / "alarm.wav"
    if not path.exists():
        path.parent.mkdir(parents=True, exist_ok=True)
        with wave.open(str(path), "wb") as f:
            f.setnchannels(1)
            f.setsampwidth(2)
            f.setframerate(RATE)
            f.writeframes(alarm_tone().tobytes())
    log.info("ringing on the Mac: %s", item["kind"])
    for _ in range(3):
        await (await asyncio.create_subprocess_exec("afplay", str(path))).wait()
    await (await asyncio.create_subprocess_exec("say", "-v", i18n.L.tts_voice, ring_sentence(item))).wait()


# --- Understanding a sentence ---

def quick(text: str) -> str | None:
    """The sentence to say if it is a skill said in a usual way; None otherwise."""
    if not enabled():
        return None
    toks = tokens(text)
    said = {t.plain for t in toks}
    kind = next((k for k in timers.KINDS if said & words(k)), None)
    when = clock(toks)
    span = duration(toks)

    if said & words("volume"):
        return _volume(toks, said)
    if kind and said & words("cancel"):
        return cancel(None if said & words("all") else kind)
    if said & words("remaining") and (kind == "timer" or said & words("math")) and not span:
        return remaining()
    if kind and said & words("list") and not span and not when:
        return listing()
    if kind == "reminder" and (span or when):
        at = time.time() + span.value if span and not when else resolve(when.value)
        label = _label(toks, span, when)
        return set_reminder(at, label) if label else set_timer(span.value) if span else None
    if kind == "alarm" and when:
        return set_alarm(resolve(when.value, waking=True))
    if kind in ("timer", "alarm") and span:
        return set_timer(span.value) if kind == "timer" else set_alarm(time.time() + span.value)
    if _question(said, "time"):
        return say_time()
    if _question(said, "date"):
        return say_date()
    result = calculate(toks)
    if result is not None:
        return i18n.L("speech.math", result=spoken(result))
    found = find_conversion(toks)
    if found:
        return conversion(found[0], found[1], found[3], found[2])
    return None


def sounds_like_one(text: str) -> bool:
    """Whether a sentence quick() didn't get may still be a skill (worth asking the interpreter)."""
    said = {t.plain for t in tokens(text)}
    v = vocabulary()
    hints = set().union(*(words(k) for k in ("timer", "alarm", "reminder", "volume", "snooze")))
    hints |= {w for names in v["durations"].values() for w in names}
    return bool(said & hints)


def _volume(toks: list[Token], said: set[str]) -> str:
    from skills.parse import number

    current = settings.get("volume") or 100
    amount = next((number(toks, i)[0] for i in range(len(toks)) if number(toks, i) and toks[i].plain[0].isdigit()
                   or number(toks, i) and toks[i].plain not in ("un", "una", "a", "an")), None)
    if said & words("max"):
        return set_volume(100)
    if said & words("min"):
        return set_volume(10)
    if amount is not None:
        return set_volume(amount)
    if said & words("down"):
        return set_volume(current - VOLUME_STEP)
    if said & words("up"):
        return set_volume(current + VOLUME_STEP)
    return None  # «el volumen está demasiado alto»: for the interpreter or the LLM


def _question(said: set[str], topic: str) -> bool:
    """«¿Qué hora es?», «what's the date?»: short, and only those words."""
    allowed = words(topic) | words("ask") | words("today") | {
        "es", "son", "it", "is", "now", "ahora", "la", "the", "me", "tell", "current", "actual", "do", "you",
        "know", "sabes", "hoy", "s", "of", "what", "estamos", "a", "el"}
    return bool(said & words(topic)) and bool(said & words("ask")) and said <= allowed and len(said) <= 6


def _label(toks: list[Token], span, when) -> str:
    """What to remind: the words that aren't the command, the time or the day."""
    used = set(day_tokens(toks))
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
