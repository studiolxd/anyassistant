"""An LLM as an interpreter for skills said in an unusual way.

«Avísame dentro de un rato largo, como 40 minutos» doesn't fit the skills'
patterns; a model turns it into data ({"skill": "timer", "seconds": 2400}) that
the same skills execute. The plugin «interpreter» (turn it off to never ask), and
settings «interpreter»: "auto" (a local model if there is one: Apple's on a Mac
with it; elsewhere, nothing) or the name of any LLM plugin that can answer outside
a conversation (complete()): "apple", "claude"…
Only for sentences that sound like a skill (sounds_like_one): the rest go
straight to the LLM.
"""

import json
import logging
import re
import time

import i18n
import kernel
import options
import settings
import skills
from options import Option
from skills import parse
from skills.parse import tokens, vocabulary, words

log = logging.getLogger("skills")
_model = None

PROMPT = """Turn the request to a voice assistant into JSON, nothing else.
{{"skill": "timer" | "alarm" | "reminder" | "cancel" | "remaining" | "list" | "time" | "date" | "volume" | "none",
 "seconds": seconds from now (a timer, or an alarm or reminder «in …»),
 "hour": 0-23, "minute": 0-59, "day": 0 today, 1 tomorrow, 2 the day after (an alarm or reminder at a time),
 "text": what to remind, in the user's words, if there is something (reminder),
 "kind": "timer", "alarm", "reminder" or "all" (cancel),
 "volume": 5-100, "up" or "down"}}
Leave out the fields that don't apply. "none" if it is anything else. It is now {now}.
Example: «{said}» → {answer}

Request: «{text}»"""


LOCAL = ["apple"]  # what «auto» tries, in order: models that run on this computer


def _llms():
    import llm

    return list(llm.available())


options.add(Option("interpreter", "auto", "an LLM for skills said in unusual ways: auto (a local one if there is: "
                   "Apple's on a Mac with it) or an LLM's name", "skills", "choice",
                   lambda: ["auto", "off"] + _llms(), live=True))


def sounds_like_one(text: str) -> bool:
    """Whether a sentence no skill took may still be one (worth asking the interpreter)."""
    said = {t.plain for t in tokens(text)}
    v = vocabulary()
    hints = set().union(*(words(k) for k in ("timer", "alarm", "reminder", "volume", "snooze")))
    hints |= {w for names in v["durations"].values() for w in names}
    return bool(said & hints)


def chosen() -> str | None:
    """The LLM plugin that interprets, or None."""
    import llm

    mode = settings.get("interpreter") or "auto"
    if mode == "off" or not skills.enabled() or not kernel.enabled("interpreter"):
        return None
    candidates = LOCAL if mode == "auto" else [mode]
    return next((name for name in candidates if name in llm.available() and llm.ready(name) is None), None)


def enabled() -> bool:
    return chosen() is not None


async def interpret(text: str) -> str | None:
    """The sentence to say, if the model understood a skill in it; None otherwise."""
    global _model
    if not enabled() or not skills.sounds_like_one(text):
        return None
    try:
        name = chosen()
        if _model is None or _model.name != name:
            import llm

            _model = llm.create(name)
        example = i18n.L.data["skills"]["interpreter_example"]
        answer = await _model.complete(PROMPT.format(
            now=time.strftime("%A %Y-%m-%d %H:%M"), said=example["said"],
            answer=json.dumps(example["answer"], ensure_ascii=False), text=text))
        match = re.search(r"\{.*\}", answer, re.S)
        data = json.loads(match.group()) if match else {}
        log.info("interpreter: %s", settings.private(json.dumps(data, ensure_ascii=False)))
        return execute(data)
    except Exception as e:  # the interpreter must never break the conversation
        log.warning("interpreter: %r", e)
        return None


def execute(data: dict) -> str | None:
    """Runs a skill from the interpreter's data (or anyone's); None if it isn't one, lacks something,
    or its plugin is off."""
    alarms, clock, volume = (kernel.module(p) for p in ("skill-alarms", "skill-clock", "skill-volume"))
    skill = data.get("skill")
    if skill in ("alarm", "reminder", "timer", "cancel", "remaining", "list") and not alarms:
        return None
    if (skill in ("time", "date") and not clock) or (skill == "volume" and not volume):
        return None
    number = lambda key: float(data[key]) if isinstance(data.get(key), (int, float)) else None  # noqa: E731
    seconds, hour = number("seconds"), number("hour")
    if skill in ("alarm", "reminder"):
        if hour is not None:
            when = parse.Clock(int(hour) % 24, int(number("minute") or 0), None, int(number("day") or 0))
            at = parse.resolve(when, waking=skill == "alarm") if number("day") is not None else alarms.next_time(int(hour), when.minute)
        elif seconds:
            at = time.time() + seconds
        else:
            return None
        if skill == "alarm":
            return alarms.set_alarm(at)
        text = str(data.get("text") or "").strip()
        if {t.plain for t in parse.tokens(text)} <= parse.words("reminder"):
            text = ""  # «Avísame»: nothing to remind, just a timer
        return alarms.set_reminder(at, text) if text else alarms.set_timer(at - time.time())
    if skill == "timer" and seconds:
        return alarms.set_timer(seconds, str(data.get("text") or ""))
    if skill == "cancel":
        kind = data.get("kind")
        return alarms.cancel(kind if kind in ("timer", "alarm", "reminder") else None)
    if skill == "remaining":
        return alarms.remaining()
    if skill == "list":
        return alarms.listing()
    if skill == "time":
        return clock.say_time()
    if skill == "date":
        return clock.say_date()
    if skill == "volume":
        level = data.get("volume")
        current = settings.get("volume") or 100
        if level in ("up", "down"):
            return volume.set_volume(current + (volume.STEP if level == "up" else -volume.STEP))
        if isinstance(level, (int, float)):
            return volume.set_volume(level)
    return None


