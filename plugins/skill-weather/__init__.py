"""The weather, without the LLM: «¿qué tiempo hace?», «¿va a llover mañana?», «el tiempo en
Madrid». From Open-Meteo (open-meteo.com: free, no account, no key): first the place's
coordinates (its geocoding), then the forecast.

Your place: settings «location» (a city; the installer asks for it), or the one you say.
How it is asked and said is in this plugin's locales (weather.*, speech.*, sky.*: the
WMO codes). The LLM has it too, as a tool.
"""

import asyncio
import json
import logging
import re
import unicodedata
import urllib.parse
import urllib.request

import i18n
import installer
import options
import settings
from options import Option
from skills import Skill, skill
from tools import ToolError, tool

log = logging.getLogger("skills")
GEOCODING = "https://geocoding-api.open-meteo.com/v1/search"
FORECAST = "https://api.open-meteo.com/v1/forecast"
TIMEOUT = 8  # seconds
_places: dict[tuple[str, str], tuple[float, float, str] | None] = {}

options.add(Option("location", None, "your city, for the weather (e.g. Valencia)", "skills", "text", live=True,
                   empty="none: you say the city"))


@installer.question("location", "City", order=63,
                    default=lambda: settings.load().get("location") or "",
                    help="For the weather. If you leave it empty, you'll have to say the city each time.")
def _install(value):
    settings.save(location=(str(value).strip() or None))


def _plain(text: str) -> str:
    """Lowercase, no accents, punctuation as spaces, the same length: a match's position is the
    original words' («Málaga» stays «Málaga»)."""
    return "".join(" " if c in "¿?¡!.,;:\"«»'’" else unicodedata.normalize("NFD", c)[0] for c in text.lower())


def understood(text: str) -> dict | None:
    """A weather question: {"day": 0|1|2, "rain": bool, "city": str|None}; None if it isn't one."""
    words = i18n.L.data["weather"]
    plain = _plain(text)
    pattern = r"^\s*" + words["ask"].strip("^$").replace(" ", r"\s+") + r"\s*$"
    found = re.match(pattern, plain)
    if not found:
        return None
    spaced = " ".join(plain.split())
    day = 2 if any(w in spaced for w in words["after_tomorrow"]) else 1 if any(
        re.search(rf"\b{w}\b", spaced) for w in words["tomorrow"]) else 0
    rain = any(re.search(rf"\b{w}\b", spaced) for w in words["rain"])
    city = text[found.start("city"):found.end("city")].strip() if found.group("city") else None
    return {"day": day, "rain": rain, "city": city}


def _get(url: str, params: dict) -> dict:
    with urllib.request.urlopen(f"{url}?{urllib.parse.urlencode(params)}", timeout=TIMEOUT) as r:
        return json.load(r)


def place(name: str) -> tuple[float, float, str] | None:
    """A city's coordinates and its name as Open-Meteo says it (kept while running)."""
    key = (name.lower(), i18n.L.code)
    if key not in _places:
        results = _get(GEOCODING, {"name": name, "count": 1, "language": i18n.L.code}).get("results") or []
        _places[key] = (results[0]["latitude"], results[0]["longitude"], results[0]["name"]) if results else None
    return _places[key]


def forecast(latitude: float, longitude: float) -> dict:
    return _get(FORECAST, {"latitude": latitude, "longitude": longitude, "timezone": "auto", "forecast_days": 3,
                           "current": "temperature_2m,weather_code",
                           "daily": "temperature_2m_max,temperature_2m_min,precipitation_probability_max,"
                                    "weather_code"})


def sky(code) -> str:
    return i18n.L.data["sky"].get(str(int(code or 0)), "")


def said(data: dict, name: str, day: int, rain: bool) -> str:
    """The sentence: now and today, a day ahead, or whether it will rain."""
    daily = data["daily"]
    when = i18n.L(("speech.weather_today", "speech.weather_tomorrow", "speech.weather_after")[day])
    chance = round(daily["precipitation_probability_max"][day] or 0)
    if rain:
        key = "speech.rain_yes" if chance >= 60 else "speech.rain_maybe" if chance >= 30 else "speech.rain_no"
        return i18n.L(key, when=when, place=name, rain=chance)
    day_text = i18n.L("speech.weather_day", when=when, place=name, low=round(daily["temperature_2m_min"][day]),
                      high=round(daily["temperature_2m_max"][day]), sky=sky(daily["weather_code"][day]), rain=chance)
    if day:
        return day_text
    now = data["current"]
    rest = i18n.L("speech.weather_rest_of_today", low=round(daily["temperature_2m_min"][0]),
                  high=round(daily["temperature_2m_max"][0]), sky=sky(daily["weather_code"][0]), rain=chance)
    return i18n.L("speech.weather_now", place=name, temp=round(now["temperature_2m"]),
                  sky=sky(now["weather_code"])) + " " + rest


def answer(day: int = 0, rain: bool = False, city: str | None = None) -> str:
    """The sentence (it asks Open-Meteo: up to a few seconds; the skill does it in the background)."""
    wanted = city or settings.get("location")
    if not wanted:
        return i18n.L("speech.weather_where")
    try:
        found = place(wanted)
        if not found:
            return i18n.L("speech.weather_unknown_place", place=wanted)
        latitude, longitude, name = found
        return said(forecast(latitude, longitude), name, day, rain)
    except (OSError, KeyError, IndexError, ValueError) as e:  # urllib's errors are OSErrors
        log.warning("weather: %r", e)
        return i18n.L("speech.weather_failed")


@skill
class Weather(Skill):
    order = 45

    def hear(self, text, assistant) -> bool:
        asked = understood(text)
        if asked is None:
            return False
        assistant.show_heard(text)

        async def reply():
            assistant.say(await asyncio.get_running_loop().run_in_executor(None, lambda: answer(**asked)))

        assistant.later(reply())
        return True


@tool("The weather now and the forecast for today, tomorrow or the day after (day 0, 1, 2), at the user's "
      "place or at a city.")
def get_weather(day: int = 0, city: str = "") -> str:
    if day not in (0, 1, 2):
        raise ToolError("day: 0 (today), 1 (tomorrow) or 2")
    return answer(day, False, city or None)
