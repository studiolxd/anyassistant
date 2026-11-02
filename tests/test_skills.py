"""Local skills without an LLM: what they understand and what they do."""

import json
import time

import pytest

import i18n
import kernel
import settings
import skills
import tools
from conftest import here, load_script
from plugins.skill_alarms import timers
import plugins.skills_language as language

interpreter = kernel.load("interpreter")
from plugins.skill_arithmetic.calc import calculate
from plugins.skills_language import spoken_number as spoken
from plugins.skills_language.parse import Clock, clock, duration, number, resolve, tokens
from plugins.skill_conversion.units import convert


@pytest.fixture
def store(tmp_path, monkeypatch):
    monkeypatch.setattr(timers, "PATH", tmp_path / "timers.json")
    monkeypatch.setattr(settings, "PATH", tmp_path / "settings.json")
    monkeypatch.setattr(settings, "active", {"volume": 80})
    return tmp_path / "timers.json"


@pytest.fixture
def noon(monkeypatch):
    """Today at midday: «in 20 minutes» is still today, whenever the tests run (near midnight it wasn't)."""
    now = time.localtime()
    fixed = time.mktime((now.tm_year, now.tm_mon, now.tm_mday, 12, 0, 0, 0, 0, -1))
    localtime = time.localtime
    monkeypatch.setattr(time, "time", lambda: fixed)
    monkeypatch.setattr(time, "localtime", lambda at=None: localtime(fixed if at is None else at))


@pytest.mark.parametrize("text, seconds", [
    ("pon un temporizador de 10 minutos", 600), ("temporizador de media hora", 1800), ("un cuarto de hora", 900),
    ("hora y media", 5400), ("1 hora y 20 minutos", 4800), ("treinta y cinco segundos", 35),
    ("tres cuartos de hora", 2700), ("qué hora es", None),
])
def test_durations_es(es, text, seconds):
    span = duration(tokens(text))
    assert (span.value if span else None) == seconds


@pytest.mark.parametrize("text, seconds", [
    ("set a timer for ten minutes", 600), ("half an hour", 1800), ("a quarter of an hour", 900),
    ("an hour and a half", 5400), ("90 seconds", 90), ("twenty five minutes", 1500),
])
def test_durations_en(en, text, seconds):
    assert duration(tokens(text)).value == seconds


@pytest.mark.parametrize("text, expected", [
    ("a las 7 y media de la tarde", Clock(7, 30, "pm", None)), ("despiértame mañana a las 7", Clock(7, 0, None, 1)),
    ("a las 8 menos cuarto", Clock(7, 45, None, None)), ("a las 19:30", Clock(19, 30, None, None)),
    ("pasado mañana a las 10 de la mañana", Clock(10, 0, "am", 2)), ("a mediodía", Clock(12, 0, None, None)),
    # In words, as the voice is written: «y» is the minutes, not 7 + 5 (it set them at 12 and 8).
    ("pongo una alarma a las siete y cinco", Clock(7, 5, None, None)),
    ("pon una alarma a las siete y un minuto", Clock(7, 1, None, None)),
    ("a las nueve y veinticinco", Clock(9, 25, None, None)), ("a las siete y media", Clock(7, 30, None, None)),
])
def test_clock_es(es, text, expected):
    assert clock(tokens(text)).value == expected


@pytest.mark.parametrize("text, expected", [
    ("at 7:30 pm", Clock(7, 30, "pm", None)), ("at half past seven", Clock(7, 30, None, None)),
    ("at quarter to eight", Clock(7, 45, None, None)), ("tomorrow at 6 am", Clock(6, 0, "am", 1)),
    ("at 7 in the morning", Clock(7, 0, "am", None)),
])
def test_clock_en(en, text, expected):
    assert clock(tokens(text)).value == expected


def test_resolve_picks_the_next_one():
    now = time.mktime((2026, 10, 31, 15, 0, 0, 0, 0, -1))  # 3 pm
    assert time.localtime(resolve(Clock(7, 0, None, None), now)).tm_hour == 19  # 7 pm today
    assert time.localtime(resolve(Clock(16, 0, None, None), now)).tm_mday == 31
    assert time.localtime(resolve(Clock(9, 0, None, None), now)).tm_hour == 21  # 9 pm, the next 9
    assert time.localtime(resolve(Clock(9, 0, "am", None), now)).tm_mday == 1  # 9 am: tomorrow
    assert time.localtime(resolve(Clock(5, 0, None, 1), now)).tm_hour == 17  # «mañana a las 5»
    assert time.localtime(resolve(Clock(5, 0, None, 1), now, waking=True)).tm_hour == 5  # «despiértame…»


@pytest.mark.parametrize("text, result", [
    ("cuánto es 23 por 47", "1081"), ("cuánto es 15 por ciento de 80", "12"), ("calcula 2 elevado a 10", "1024"),
    ("cuánto son 3,5 más 2", "5,5"), ("cuánto es 10 entre 4", "2,5"), ("cuánto es cinco al cuadrado", "25"),
    ("cuánto es el temporizador", None), ("cuánto cuesta un piso", None),
])
def test_math_es(es, text, result):
    value = calculate(tokens(text))
    assert (spoken(value) if value is not None else None) == result


@pytest.mark.parametrize("text, result", [
    ("what's 23 times 47", "1081"), ("what's 15 percent of 80", "12"), ("what is 2 to the power of 8", "256"),
    ("how much is twelve plus thirty", "42"),
])
def test_math_en(en, text, result):
    assert spoken(calculate(tokens(text))) == result


@pytest.mark.parametrize("text, source, target, result", [
    ("cuántos kilómetros son 5 millas", "mi", "km", 8.05), ("convierte 20 grados a fahrenheit", "c", "f", 68),
    ("cuántos grados fahrenheit son 20 grados", "c", "f", 68), ("pasa 3 kilos a libras", "kg", "lb", 6.61),
])
def test_units_es(es, text, source, target, result):
    value, src, converted, dst = convert(tokens(text))
    assert (src, dst, round(converted, 2)) == (source, target, result)


def test_units_en(en):
    assert round(convert(tokens("how many centimeters in 5 inches"))[2], 2) == 12.7
    assert convert(tokens("how old are you")) is None


def test_time_es(store, es):
    assert skills.quick("¿Qué hora es?").startswith(("Son las", "Es la"))  # «Es la 1…» from 1 to 1:59


@pytest.mark.parametrize("text, starts", [
    ("¿Qué día es hoy?", "Hoy es"), ("Pon un temporizador de 10 minutos", "Temporizador de 10 minutos"),
    ("Avísame en 5 minutos", "Temporizador de 5 minutos"), ("Despiértame mañana a las 7", "Alarma para mañana a las 7"),
    ("Recuérdame en 20 minutos que saque la ropa", "Te lo recordaré hoy"), ("Cuánto es 23 por 47", "Son 1081"),
    ("Cuántos kilómetros son 5 millas", "5 millas son 8,05 kilómetros"), ("Pon el volumen al 70", "Volumen al 70"),
])
def test_quick_es(store, es, noon, text, starts):
    assert skills.quick(text).startswith(starts)


@pytest.mark.parametrize("text", [
    "¿A qué hora abre el museo?", "¿Qué hora es en Tokio?", "¿Cuánto cuesta el piso?", "El volumen está demasiado alto",
    "¿Qué tal estás?", "Pon la cara redonda",
])
def test_not_skills_es(store, es, text):
    assert skills.quick(text) is None


def test_quick_en(store, en):
    assert skills.quick("What time is it?").startswith("It's")
    assert skills.quick("Remind me to call mom at 6 pm").endswith("at 6:00 pm: call mom.")
    assert skills.quick("Wake me up tomorrow at 7").startswith("Alarm set for tomorrow at 7:00 am")


def test_reminder_labels(store, es):
    skills.quick("Quiero que me recuerdes a las nueve de la noche sacar la basura")
    skills.quick("Recuérdame que llame a mamá mañana a las 6")
    skills.quick("Avísame dentro de un rato largo, como tres cuartos de hora")  # no «que»: a timer
    # As a set: after 9 pm, «a las nueve de la noche» is tomorrow and comes after «mañana a las 6».
    assert {(i["kind"], i["label"]) for i in timers.pending() if i["kind"] != "timer"} == {
        ("reminder", "sacar la basura"), ("reminder", "llame a mamá")}


def test_list_remaining_cancel(store, es):
    assert skills.quick("¿Cuánto queda?") == "No hay nada en marcha."
    skills.quick("Pon un temporizador de 10 minutos")
    skills.quick("Pon una alarma a las 7 y media")
    assert skills.quick("¿Cuánto queda?").startswith("Quedan 9 minutos") or skills.quick("¿Cuánto queda?").startswith("Quedan 10")
    assert "un temporizador" in skills.quick("¿Qué alarmas tengo?")
    assert skills.quick("Cancela las alarmas") == "Cancelado."
    assert [i["kind"] for i in timers.pending()] == ["timer"]
    assert skills.quick("Cancela todos los temporizadores") == "Cancelado."
    assert skills.quick("Cancela la alarma") == "No había nada que cancelar."


def test_volume(store, es):
    assert skills.quick("Baja el volumen") == "Volumen al 60 por ciento."
    assert skills.quick("Sube el volumen al máximo") == "Volumen al 100 por ciento."
    assert json.loads(settings.PATH.read_text())["volume"] == 100


def test_due_timers_leave_the_list(store):
    timers.add("timer", time.time() - 1)
    timers.add("alarm", time.time() + 100)
    assert [i["kind"] for i in timers.due()] == ["timer"]
    assert [i["kind"] for i in timers.pending()] == ["alarm"]


def test_skills_can_be_turned_off(store, es):
    settings.active["skills"] = False
    assert skills.quick("¿Qué hora es?") is None


def test_interpreter_is_configurable(store, monkeypatch):
    import llm

    monkeypatch.setattr(llm, "ready", lambda name: "not on this Mac")
    assert not interpreter.enabled()  # auto, without Apple's model
    monkeypatch.setattr(llm, "ready", lambda name: None)
    assert interpreter.enabled() == here("llm-apple")  # auto: a local model (Apple's, only on the Mac)
    settings.active["interpreter"] = "off"
    assert not interpreter.enabled()
    settings.active["interpreter"] = "claude"  # any LLM that can answer outside a conversation
    assert interpreter.chosen() == "claude"


def test_interpreter_data_runs_the_skills(store, es):
    assert interpreter.execute({"skill": "timer", "seconds": 2700}) == "Temporizador de 45 minutos."
    assert interpreter.execute({"skill": "reminder", "seconds": 60, "text": "Avísame"}).startswith("Temporizador")
    assert interpreter.execute({"skill": "alarm", "hour": 6, "minute": 50, "day": 1}) == \
        "Alarma para mañana a las 6 y 50 de la mañana."
    assert interpreter.execute({"skill": "volume", "volume": "down"}) == "Volumen al 60 por ciento."
    assert interpreter.execute({"skill": "none"}) is None


def test_tools_without_confirmation(store, es):
    assert tools.call("set_timer", {"seconds": 300}) == "Temporizador de 5 minutos."
    assert tools.call("set_reminder", {"text": "regar las plantas", "seconds": 600}).endswith("regar las plantas.")
    assert "un temporizador" in tools.call("list_timers", {})
    assert tools.call("cancel_timers", {"kind": "all"}) == "Cancelado."
    hook = load_script("anyassistant-confirm")
    for name in ("set_timer", "set_alarm", "set_reminder", "cancel_timers", "set_volume"):
        assert hook.describe(f"mcp__anyassistant__{name}", {}) is None


def test_spoken_durations(es):
    assert language.spoken_duration(90) == "1 minuto y 30 segundos"
    assert language.spoken_duration(3720) == "1 hora y 2 minutos"
    i18n.use("en")
    assert language.spoken_duration(7205) == "2 hours"


def test_only_meant_words_stop_the_alarm(es):
    from plugins.skill_ringing import stops_it

    assert stops_it("Para") and stops_it("Apaga la alarma") and stops_it("Vale")
    assert not stops_it("Kimbo.")  # its own tone, transcribed
    assert not stops_it("Gracias")


@pytest.mark.parametrize("text, value", [
    ("treinta y cinco", 35), ("noventa y nueve", 99), ("siete y cinco", 7), ("veinte y treinta", 20),
])
def test_numbers_joined_es(es, text, value):
    assert number(tokens(text), 0)[0] == value


@pytest.mark.parametrize("text, value", [
    ("two hundred and five", 205), ("a thousand and twenty", 1020), ("seven and five", 7),
])
def test_numbers_joined_en(en, text, value):
    assert number(tokens(text), 0)[0] == value


def test_an_alarm_in_words_at_its_minute(store, es, monkeypatch):
    """At 19:03, «a las siete y cinco» is 19:05 today (it was set at midnight: 7 + 5)."""
    now = time.localtime()
    fixed = time.mktime((now.tm_year, now.tm_mon, now.tm_mday, 19, 3, 0, 0, 0, -1))
    localtime = time.localtime
    monkeypatch.setattr(time, "time", lambda: fixed)
    monkeypatch.setattr(time, "localtime", lambda at=None: localtime(fixed if at is None else at))
    skills.quick("Pongo una alarma a las siete y cinco.")
    assert [(i["kind"], i["at"]) for i in timers.pending()] == [("alarm", fixed + 120)]

