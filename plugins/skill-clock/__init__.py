"""«¿Qué hora es?», «¿qué día es hoy?»: at once, without the LLM."""

import time

import i18n
from skills import Skill, skill
from plugins.skills_language.parse import words


def say_time() -> str:
    t = time.localtime()
    one = t.tm_hour % 12 == 1
    return i18n.L("speech.time_is_one" if one else "speech.time_is", time=i18n.L.time_spoken(t))


def say_date() -> str:
    return i18n.L("speech.date_is", date=i18n.L.date_spoken())


def asked(said: set[str], topic: str) -> bool:
    """«¿Qué hora es?», «what's the date?»: short, and only those words («¿qué hora es en Tokio?» isn't)."""
    allowed = words(topic) | words("ask") | words("today") | {
        "es", "son", "it", "is", "now", "ahora", "la", "the", "me", "tell", "current", "actual", "do", "you",
        "know", "sabes", "hoy", "s", "of", "what", "estamos", "a", "el"}
    return bool(said & words(topic)) and bool(said & words("ask")) and said <= allowed and len(said) <= 6


@skill
class Clock(Skill):
    order = 32
    harmless = True

    def answer(self, text, toks):
        said = {t.plain for t in toks}
        if asked(said, "time"):
            return say_time()
        if asked(said, "date"):
            return say_date()
        return None
