import json
import re
import time

import pytest

import i18n
from conftest import ROOT

# Keys only some languages need: the "periods" style of telling the time.
# And vocabularies keyed by the language's own words («mil», «media»).
STYLE_KEYS = re.compile(r"^calendar\.(periods\.|article_|on_the_hour|past_the_hour|minutes_named\.)"
                        r"|^skills\.(numbers|fractions|multipliers)\.|^skills\.clock\.morning$")


def flatten(data, prefix=""):
    out = {}
    for key, value in data.items():
        if isinstance(value, dict):
            out.update(flatten(value, f"{prefix}{key}."))
        else:
            out[prefix + key] = value
    return out


def placeholders(value):
    return set(re.findall(r"\{(\w+)\}", value)) if isinstance(value, str) else set()


BASE = flatten(json.loads((ROOT / "locales" / "en.json").read_text()))
OTHERS = [code for code in i18n.available() if code != "en"]


def test_english_is_available():
    assert "en" in i18n.available()


@pytest.mark.parametrize("code", OTHERS)
def test_no_unknown_keys(code):
    """Every key of a translation exists in English (catches typos), except style keys."""
    data = flatten(json.loads((ROOT / "locales" / f"{code}.json").read_text()))
    unknown = {k for k in data.keys() - BASE.keys() if not STYLE_KEYS.match(k)}
    assert not unknown


@pytest.mark.parametrize("code", OTHERS)
def test_same_placeholders(code):
    """«{wake}», «{error}»… must survive the translation, or format() breaks."""
    data = flatten(json.loads((ROOT / "locales" / f"{code}.json").read_text()))
    for key, value in data.items():
        # The calendar's formats depend on the style of telling the time, not on English.
        if key in BASE and isinstance(value, str) and not key.startswith("calendar."):
            assert placeholders(value) == placeholders(BASE[key]), key


def test_missing_keys_fall_back_to_english(tmp_path, monkeypatch):
    (tmp_path / "en.json").write_text(json.dumps({"language_name": "English", "a": {"b": "B", "c": "C"}}))
    (tmp_path / "xx.json").write_text(json.dumps({"language_name": "Xish", "a": {"b": "Xb"}}))
    monkeypatch.setattr(i18n, "LOCALES", tmp_path)
    locale = i18n.Locale("xx")
    assert locale("a.b") == "Xb"
    assert locale("a.c") == "C"
    assert locale.name == "Xish"


def test_unknown_language_is_refused():
    with pytest.raises(ValueError):
        i18n.use("zz")


def test_values_are_filled_in(lang):
    assert "{" not in i18n.L("ui.asleep", wake="Hey Jarvis")


def moment(hour, minute, weekday=4, day=30, month=10, year=2026):
    return time.struct_time((year, month, day, hour, minute, 0, weekday, 303, 0))


def test_spoken_time_english(en):
    assert i18n._spoken_now(i18n.L, moment(20, 42)) == "Friday, October 30, 2026, 8:42 pm"
    assert i18n._spoken_now(i18n.L, moment(0, 5)).endswith("12:05 am")


@pytest.mark.parametrize("hour, minute, expected", [
    (20, 42, "las 8 y 42 de la noche"),
    (13, 0, "la 1 en punto de la tarde"),
    (9, 15, "de la mañana"),
    (3, 0, "de la madrugada"),
])
def test_spoken_time_spanish(es, hour, minute, expected):
    assert expected in i18n._spoken_now(i18n.L, moment(hour, minute))


def test_variants_are_picked_at_random_without_repeating(es):
    said = [i18n.L("speech.wait") for _ in range(30)]
    assert len(set(said)) > 2
    assert all(a != b for a, b in zip(said, said[1:]))
    assert all(s in i18n.L.list("speech.wait") for s in said)


PLUGIN_TEXTS = sorted(p for p in (ROOT / "plugins").glob("*/locales/es.json"))
META = {"plugins", "options", "installer"}  # their English is in the code (plugin.json, the Option, the step)


@pytest.mark.parametrize("path", PLUGIN_TEXTS, ids=lambda p: p.parent.parent.name)
def test_a_plugins_spanish_has_its_english(path):
    """What a plugin says in Spanish it says in English too (in its own locales/en.json)."""
    spanish = {k: v for k, v in json.loads(path.read_text()).items() if k not in META}
    english_file = path.with_name("en.json")
    english = json.loads(english_file.read_text()) if english_file.exists() else {}
    missing = {k for k in flatten(spanish).keys() - flatten(english).keys() if not STYLE_KEYS.match(k)
               and ".names." not in k and ".display." not in k}  # words of each language: «compra», «shopping»
    assert not missing
