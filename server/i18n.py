"""Localization: everything Jarvis says, shows or understands, per language.

Texts live in locales/<code>.json. English (en.json) is the base: any key missing
from another language falls back to it, so adding a language is adding a file.
The language comes from --lang or, by default, the Mac's preferred language when
there is a locale for it.

Modules read the active locale at call time (`i18n.L("speech.wait")`), never at
import time, so it can be chosen after they are loaded.

A sentence can also be a list of variants («One moment, let me check.», «Let me
look.»…): each time one is picked at random, never the same twice in a row. To
add or change them, edit the locale; each language has its own.
"""

import json
import logging
import os
import random
import re
import subprocess
import time

import paths

LOCALES = paths.LOCALES
log = logging.getLogger("i18n")


def available() -> list[str]:
    return sorted(p.stem for p in LOCALES.glob("*.json"))


def detect() -> str:
    """The Mac's preferred language (or $LANG) if there is a locale for it; else English."""
    candidates = []
    try:
        output = subprocess.run(
            ["defaults", "read", "-g", "AppleLanguages"], capture_output=True, text=True, timeout=5
        ).stdout
        candidates += re.findall(r'"?([a-z]{2})[-_",\s]', output)
    except (OSError, subprocess.TimeoutExpired):
        pass
    candidates += [os.environ.get(v, "")[:2].lower() for v in ("LC_ALL", "LANG")]
    return next((c for c in candidates if c in available()), "en")


def _merge(base: dict, extra: dict) -> dict:
    merged = dict(base)
    for key, value in extra.items():
        merged[key] = _merge(base[key], value) if isinstance(value, dict) and isinstance(base.get(key), dict) else value
    return merged


class Locale:
    def __init__(self, code: str):
        data = json.loads((LOCALES / "en.json").read_text())
        if code != "en":
            data = _merge(data, json.loads((LOCALES / f"{code}.json").read_text()))
        self.code = code
        self.data = data
        self._last = {}  # key → the variant said last time

    def _get(self, key: str):
        value = self.data
        for part in key.split("."):
            value = value[part]
        return value

    def __call__(self, key: str, **values) -> str:
        """A text, filled in: L("speech.hermes_approval", action="…"); a random variant if it is a list."""
        text = self._get(key)
        if isinstance(text, list):
            choices = [t for t in text if t != self._last.get(key)] or text
            text = self._last[key] = random.choice(choices)
        return text.format(**values)

    def list(self, key: str) -> list[str]:
        return list(self._get(key))

    @property
    def name(self) -> str:
        """The language's name in English, for the LLM («Reply in Spanish»)."""
        return self.data["language_name"]

    @property
    def stt_language(self) -> str:
        return self.data["stt_language"]

    @property
    def tts_voice(self) -> str:
        return self.data["tts_voice"]

    def now_spoken(self) -> str:
        """Date and time as one would say them («Friday, October 30, 2026, 8:42 pm»)."""
        return _spoken_now(self, time.localtime())

    def time_spoken(self, t=None) -> str:
        """Just the time («8:42 pm», «las 8 y 42 de la noche»): calendar.time_format."""
        return self.data["calendar"]["time_format"].format(**_calendar(self, t or time.localtime()))

    def date_spoken(self, t=None) -> str:
        """Just the date («Friday, October 30»): calendar.date_format."""
        return self.data["calendar"]["date_format"].format(**_calendar(self, t or time.localtime()))


def _spoken_now(locale: Locale, t) -> str:
    return locale.data["calendar"]["now_format"].format(**_calendar(locale, t))


def _calendar(locale: Locale, t) -> dict:
    """The current date and time following the locale's calendar.now_format.

    Two styles, chosen by calendar.now_style:
    - "ampm": 12-hour clock with am/pm («8:42 pm»).
    - "periods": 12-hour clock with day periods and spoken minutes («las 8 y 42 de
      la noche»): with «20:42» small models stumble reading it aloud.
    """
    cal = locale.data["calendar"]
    hour = t.tm_hour % 12 or 12
    values = {
        "weekday": cal["days"][t.tm_wday], "day": t.tm_mday, "month": cal["months"][t.tm_mon - 1],
        "year": t.tm_year, "hour": hour, "minute": f"{t.tm_min:02d}",
        "ampm": "am" if t.tm_hour < 12 else "pm",
    }
    if cal.get("now_style") == "periods":
        periods = cal["periods"]
        if 6 <= t.tm_hour < 12:
            values["period"] = periods["morning"]
        elif 12 <= t.tm_hour < 20:
            values["period"] = periods["afternoon"]
        elif t.tm_hour >= 20:
            values["period"] = periods["night"]
        else:
            values["period"] = periods["early_morning"]
        named = cal.get("minutes_named", {}).get(str(t.tm_min))  # «y media», «y cuarto»
        values["minutes"] = (cal["on_the_hour"] if t.tm_min == 0 else named
                             or cal["past_the_hour"].format(minute=t.tm_min))
        values["article"] = cal["article_one"] if hour == 1 else cal["article_other"]
    return values


L = Locale("en")


def use(code: str) -> Locale:
    """Chooses the active language."""
    global L
    if code not in available():
        raise ValueError(f"No locale «{code}». Available: {', '.join(available())}")
    L = Locale(code)
    log.info("language: %s", L.name)
    return L
