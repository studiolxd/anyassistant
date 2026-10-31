"""Understanding numbers, durations, clock times and days in a sentence, per language.

The words come from the locale («skills»: numbers, durations, clock…), so the
logic is the same for every language. Tokens keep the original word (for labels
such as «llamar a mamá») and a plain version (lowercase, no accents) to compare.
"""

import re
import time
import unicodedata
from dataclasses import dataclass

import i18n


@dataclass
class Token:
    word: str  # as said: «mamá»
    plain: str  # to compare: «mama»


def plain(text: str) -> str:
    text = unicodedata.normalize("NFKD", text.lower())
    return "".join(c for c in text if not unicodedata.combining(c))


def tokens(text: str) -> list[Token]:
    """Words, numbers (with decimals: «3,5», «3.5») and «%»."""
    found = re.finditer(r"\d+(?:[.,]\d+)?|%|[^\W\d_]+", text)
    return [Token(m.group(), plain(m.group()).replace(",", ".")) for m in found]


def vocabulary() -> dict:
    return i18n.L.data["skills"]


def words(name: str) -> set[str]:
    """A group of words («cancel», «volume»…): the core's, or the plugin's that brings them (an
    empty set if that plugin isn't there)."""
    return set(vocabulary()["words"].get(name, ()))


def number(toks: list[Token], i: int) -> tuple[float, int] | None:
    """The number starting at token i («35», «3,5», «treinta y cinco», «two hundred»): (value, next i)."""
    v = vocabulary()
    if i >= len(toks):
        return None
    if re.fullmatch(r"\d+(\.\d+)?", toks[i].plain):
        value, j = float(toks[i].plain), i + 1
        if j + 1 < len(toks) and toks[j].plain in v["decimal"] and toks[j + 1].plain.isdigit():
            value, j = float(f"{toks[i].plain.split('.')[0]}.{toks[j + 1].plain}"), j + 2
        return value, j
    total = current = 0
    found = False
    j = i
    while j < len(toks):
        word = toks[j].plain
        if word in v["numbers"]:
            value = v["numbers"][word]
            current = current * 100 if value == 100 and current else current + value
            found, j = True, j + 1
        elif word in v["multipliers"] and found:
            total += max(current, 1) * v["multipliers"][word]
            current, j = 0, j + 1
        elif word in v["joiners"] and found and j + 1 < len(toks) and toks[j + 1].plain in v["numbers"]:
            j += 1
        elif word in v["decimal"] and found and j + 1 < len(toks):
            decimals = number(toks, j + 1)
            if not decimals:
                break
            digits = str(int(decimals[0]))
            return total + current + int(digits) / 10 ** len(digits), decimals[1]
        else:
            break
    return (float(total + current), j) if found else None


def unit_seconds(word: str) -> int | None:
    for name, seconds in (("second", 1), ("minute", 60), ("hour", 3600)):
        if word in vocabulary()["durations"][name]:
            return seconds
    return None


@dataclass
class Span:
    value: object
    start: int
    end: int  # exclusive


def duration(toks: list[Token]) -> Span | None:
    """«10 minutos», «hora y media», «a quarter of an hour», «1 hora y 20 minutos» → seconds."""
    v = vocabulary()
    skip = {"de", "of", "an", "a"}
    total, start, end = 0.0, None, None
    i = 0
    while i < len(toks):
        amount = number(toks, i)
        j = amount[1] if amount else i
        value = amount[0] if amount else None
        if j < len(toks) and toks[j].plain in v["fractions"]:  # «un cuarto», «half»
            value, j = (value or 1) * v["fractions"][toks[j].plain], j + 1
        k = j
        while value is not None and k < len(toks) and toks[k].plain in skip:
            k += 1
        unit = unit_seconds(toks[k].plain) if k < len(toks) else None
        bare = value is None and unit_seconds(toks[i].plain) and _half_after(toks, i + 1)
        if bare:  # «hora y media»: the unit alone, only with a half after it
            value, unit, k = 1, unit_seconds(toks[i].plain), i
        if value is None or not unit:
            i += 1
            continue
        total += value * unit
        start = i if start is None else start
        end = k + 1
        half = _half_after(toks, k + 1)
        if half:
            total += unit / 2
            end = half
        i = end
    return Span(total, start, end) if total else None


def _half_after(toks: list[Token], i: int) -> int | None:
    """«y media», «and a half» right after: the index after it."""
    v = vocabulary()
    if i < len(toks) and toks[i].plain in v["joiners"]:
        j = i + 1
        if j < len(toks) and toks[j].plain in ("a", "an"):
            j += 1
        if j < len(toks) and v["fractions"].get(toks[j].plain) == 0.5:
            return j + 1
    return None


@dataclass
class Clock:
    hour: int
    minute: int
    period: str | None  # "am", "pm" or None
    day: int | None  # 0 today, 1 tomorrow, 2 the day after; None if not said


def clock(toks: list[Token]) -> Span | None:
    """«a las 7 y media de la tarde», «at 7:30 pm», «half past seven», «mañana a las 8» → Clock."""
    v = vocabulary()
    c, at = v["clock"], words("at")
    day, used = _day(toks)
    for i, tok in enumerate(toks):
        word = tok.plain
        if word in c.get("noon", []) or word in c.get("midnight", []):
            hour = 12 if word in c.get("noon", []) else 0
            return Span(Clock(hour, 0, None, day), i, i + 1)
        # «half past seven», «quarter to eight», «twenty past six»
        before = number(toks, i)
        if word in c["half"] or word in c["quarter"] or before:
            j = before[1] if before else i + 1
            if j + 1 < len(toks) and toks[j].plain in c["past"] + c["to"] and c["past"] != ["y"]:
                hour = number(toks, j + 1)
                if hour and 0 < hour[0] <= 24:
                    minutes = 30 if word in c["half"] else 15 if word in c["quarter"] else int(before[0])
                    h, m = int(hour[0]), minutes
                    if toks[j].plain in c["to"]:
                        h, m = h - 1, 60 - minutes
                    period, end = _period(toks, hour[1])
                    return Span(Clock(h % 24, m, period, day), i, end)
        # «a las 7…», «at 7…», or «7 pm»
        found = number(toks, i)
        if not found or not (0 <= found[0] <= 24) or (i == 0 or toks[i - 1].plain not in at) and not _period(toks, found[1])[0]:
            continue
        value, j = found
        hour, minute = int(value), round((value - int(value)) * 100)  # «7.30»
        if j < len(toks) and toks[j].plain in c["past"]:  # «y media», «y cuarto», «y 20»
            k = j + 1
            if k < len(toks) and toks[k].plain in c["half"]:
                minute, j = 30, k + 1
            elif k < len(toks) and toks[k].plain in c["quarter"]:
                minute, j = 15, k + 1
            elif number(toks, k) and number(toks, k)[0] < 60:
                minute, j = int(number(toks, k)[0]), number(toks, k)[1]
        elif j < len(toks) and toks[j].plain in c["to"] and c["past"] == ["y"]:  # «menos cuarto», «menos 10»
            k = j + 1
            less = 15 if k < len(toks) and toks[k].plain in c["quarter"] else None
            if less is None and number(toks, k):
                less = int(number(toks, k)[0])
            if less:
                hour, minute, j = hour - 1, 60 - less, (k + 1 if toks[k].plain in c["quarter"] else number(toks, k)[1])
        elif number(toks, j) and number(toks, j)[0] < 60 and minute == 0:  # «7 30», «19:30»
            minute, j = int(number(toks, j)[0]), number(toks, j)[1]
        while j < len(toks) and toks[j].plain in c["oclock"]:
            j += 1
        period, end = _period(toks, j)
        start = i
        while start and toks[start - 1].plain in at:  # «a las», «at»
            start -= 1
        return Span(Clock(hour % 24, minute, period, day), start, max(end, j))
    return None


def _period(toks: list[Token], j: int) -> tuple[str | None, int]:
    """«de la tarde», «pm», «in the morning» from token j: (am/pm, index after it)."""
    c = vocabulary()["clock"]
    k = j
    while k < len(toks) and toks[k].plain in ("de", "la", "in", "the", "at", "por"):
        k += 1
    if k < len(toks):
        word = toks[k].plain
        if word in c["am"] or word in c.get("morning", []):
            return "am", k + 1
        if word in c["pm"]:
            return "pm", k + 1
    return None, j


def _day(toks: list[Token]) -> tuple[int | None, set[int]]:
    """Today, tomorrow or the day after («pasado mañana», «the day after tomorrow»)."""
    tomorrow, today = words("tomorrow"), words("today")
    for i, tok in enumerate(toks):
        # «de la mañana» is the morning, not tomorrow
        if tok.plain in tomorrow and not (i >= 1 and toks[i - 1].plain == "la"):
            after = i >= 1 and toks[i - 1].plain in ("pasado", "after")
            return (2 if after else 1), {i, i - 1} if after else {i}
        if tok.plain in today:
            return 0, {i}
    return None, set()


def day_tokens(toks: list[Token]) -> set[int]:
    return _day(toks)[1]


def resolve(when: Clock, now: float | None = None, waking: bool = False) -> float:
    """The moment a clock time means: the next one, or on the day said.

    Without am/pm: the next of 7:00 and 19:00 if no day is said; with a day,
    1–6 means the afternoon («mañana a las 5») except for waking up.
    """
    now = now or time.time()
    today = time.localtime(now)
    midnight = time.mktime((today.tm_year, today.tm_mon, today.tm_mday, 0, 0, 0, 0, 0, -1))
    hours = [when.hour]
    if when.period == "pm" and when.hour < 12:
        hours = [when.hour + 12]
    elif when.period == "am" and when.hour == 12:
        hours = [0]
    elif when.period is None and 1 <= when.hour <= 12:
        if when.day is None:
            hours = [when.hour % 12, when.hour % 12 + 12]
        elif when.hour <= 6 and not waking:
            hours = [when.hour + 12]
    if when.day is not None:
        base = midnight + when.day * 86400
        return base + hours[0] * 3600 + when.minute * 60
    moments = [midnight + d * 86400 + h * 3600 + when.minute * 60 for d in (0, 1) for h in hours]
    return min(m for m in moments if m > now)
