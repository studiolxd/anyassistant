"""The words skills share, in each language: numbers («treinta y cinco»), durations («media
hora»), times and days («mañana a las 7»), how a list or a duration is said («leche, huevos
y pan»), and common words («hoy», «mañana»…). A library: skills that understand or say
those declare it in their plugin.json «requires». Its vocabulary is in its locales
(«skills», «speech»), so another language is another file.

    from plugins.skills_language import spoken_list, spoken_duration, spoken_when, spoken_number
    from plugins.skills_language.parse import number, duration, clock, resolve, words
"""

import time

import i18n

from .parse import vocabulary


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


def spoken_number(value: float) -> str:
    """«1081», «3,5» (the language's decimal sign), at most 2 decimals."""
    import math

    if math.isinf(value):
        return "∞"
    text = f"{value:.2f}".rstrip("0").rstrip(".")
    if text in ("-0", ""):
        text = "0"
    return text.replace(".", "," if "coma" in vocabulary()["decimal"] else ".")
