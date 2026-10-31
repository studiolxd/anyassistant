"""Skills: what Jarvis does by itself when it hears something, before (or instead of)
the LLM. Each is a module of this package with a class like this:

    @skill
    class Clock(Skill):
        order = 32                          # who listens first (lower: earlier)
        def answer(self, text, toks):       # what to say, or None if it isn't for it
            ...

…or, for those that need to do more than answer (switch the camera, restart…):

        def hear(self, text, jarvis) -> bool:   # True if it took the sentence
            jarvis.show_heard(text); jarvis.send({...}); jarvis.say("…")

`jarvis` is the assistant (brain/assistant.py): show_heard, reply, say, send,
later, restart, stop, ringing, rang, llm. A skill's tools for the LLM go in its
module with @tool (tools/). Their words are in the locale («skills», «commands»),
so another language is another file.

The local ones (time, timers, sums, units, volume) can be turned off with
settings «skills»; when one is said in an unusual way, interpreter.py may still
find it with Apple's local model.
"""

import importlib
import logging
import pkgutil
import time

import i18n
import settings
from skills.parse import Token, tokens, vocabulary, words

log = logging.getLogger("skills")
_skills: list["Skill"] = []
_loaded = False


class Skill:
    name = "?"
    order = 50
    local = True  # time, timers, sums… (settings «skills»); commands are always there

    def answer(self, text: str, toks: list[Token]) -> str | None:
        """What to say, if the sentence is for this skill; None otherwise."""
        return None

    def hear(self, text: str, jarvis) -> bool:
        """Takes the sentence if it is for this skill: by default, says its answer."""
        reply = self.answer(text, tokens(text))
        if reply is None:
            return False
        jarvis.reply(text, reply)
        return True


def skill(cls):
    """Registers a skill (one instance, in the order they listen)."""
    cls.name = cls.__name__.lower()
    _skills.append(cls())
    _skills.sort(key=lambda s: s.order)
    return cls


def load():
    """Imports every module of the package: the skills register themselves."""
    global _loaded
    if not _loaded:
        _loaded = True
        for module in pkgutil.iter_modules(__path__):
            importlib.import_module(f"{__name__}.{module.name}")


def enabled() -> bool:
    return settings.get("skills", True) is not False


def ordered() -> list[Skill]:
    load()
    return [s for s in _skills if enabled() or not s.local]


def hear(text: str, jarvis) -> bool:
    """The first skill that takes the sentence handles it; False if none does (it goes to the LLM)."""
    return any(s.hear(text, jarvis) for s in ordered())


def quick(text: str) -> str | None:
    """What a local skill would answer to it (time, timers, sums…), or None."""
    toks = tokens(text)
    for s in ordered():
        reply = s.answer(text, toks)
        if reply is not None:
            return reply
    return None


def sounds_like_one(text: str) -> bool:
    """Whether a sentence no skill took may still be one (worth asking the interpreter)."""
    said = {t.plain for t in tokens(text)}
    v = vocabulary()
    hints = set().union(*(words(k) for k in ("timer", "alarm", "reminder", "volume", "snooze")))
    hints |= {w for names in v["durations"].values() for w in names}
    return bool(said & hints)


# --- How things are said (for every skill) ---

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


def spoken_list(parts: list[str]) -> str:
    joiner = i18n.L("speech.list_and")
    return parts[0] if len(parts) == 1 else ", ".join(parts[:-1]) + joiner + parts[-1]
