"""Unit conversions: «cuántos kilómetros son 5 millas», «20 grados en fahrenheit».

Unit names per language in locale skills.units; the factors (to meters, kilos,
liters) here.
"""

from skills.calc import spoken
from skills.parse import Token, number, vocabulary, words

FACTORS = {
    "length": {"mm": 0.001, "cm": 0.01, "m": 1, "km": 1000, "in": 0.0254, "ft": 0.3048, "yd": 0.9144, "mi": 1609.344},
    "mass": {"g": 0.001, "kg": 1, "lb": 0.45359237, "oz": 0.028349523125},
    "volume": {"ml": 0.001, "l": 1, "gal": 3.785411784, "cup": 0.2365882365},
    "temperature": {"c": None, "f": None},
}


def dimension(unit: str) -> str | None:
    return next((d for d, units in FACTORS.items() if unit in units), None)


def unit_at(toks: list[Token], i: int) -> tuple[str, int] | None:
    """The unit said at token i («kilómetros», «grados fahrenheit», «grados»: "deg"): (unit, next i)."""
    if i >= len(toks):
        return None
    v = vocabulary()
    word = toks[i].plain
    if word in v["degrees"]:
        explicit = unit_at(toks, i + 1)
        return (explicit[0], explicit[1]) if explicit and dimension(explicit[0]) == "temperature" else ("deg", i + 1)
    for unit, names in v["units"].items():
        if word in names["words"]:
            return unit, i + 1
    return None


def convert(toks: list[Token]) -> tuple[float, str, float, str] | None:
    """(value, from, result, to) if the sentence asks to convert a number to another unit."""
    if not set(t.plain for t in toks) & words("convert"):
        return None
    found, source, target = None, None, None
    i = 0
    while i < len(toks):
        amount = number(toks, i) if found is None else None
        if amount:
            unit = unit_at(toks, amount[1]) or (unit_at(toks, amount[1] + 1) if amount[1] < len(toks) and toks[amount[1]].plain == "de" else None)
            if unit:
                found, source, i = amount[0], unit[0], unit[1]
                continue
        unit = unit_at(toks, i)
        if unit:
            target, i = target or unit[0], unit[1]
            continue
        i += 1
    if found is None or not source or not target:
        return None
    if source == "deg":
        source = "c" if target == "f" else "f"
    if target == "deg":
        target = "f" if source == "c" else "c"
    if source == target or dimension(source) != dimension(target) or not dimension(source):
        return None
    return found, source, _convert(found, source, target), target


def _convert(value: float, source: str, target: str) -> float:
    if dimension(source) == "temperature":
        return value * 9 / 5 + 32 if source == "c" else (value - 32) * 5 / 9
    factors = FACTORS[dimension(source)]
    return value * factors[source] / factors[target]


def name(unit: str, value: float) -> str:
    names = vocabulary()["units"][unit]
    return names["one"] if spoken(value) in ("1",) else names["other"]
