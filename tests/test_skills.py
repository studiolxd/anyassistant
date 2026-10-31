"""Local skills without an LLM: what they understand and what they do."""

import json
import time

import pytest

import i18n
import settings
import skills
import tools
from conftest import load_script
from skills import interpreter, timers
from skills.calc import calculate, spoken
from skills.parse import Clock, clock, duration, resolve, tokens
from skills.units import convert


@pytest.fixture
def store(tmp_path, monkeypatch):
    monkeypatch.setattr(timers, "PATH", tmp_path / "timers.json")
    monkeypatch.setattr(settings, "PATH", tmp_path / "settings.json")
    monkeypatch.setattr(settings, "active", {"volume": 80})
    return tmp_path / "timers.json"


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


@pytest.mark.parametrize("text, starts", [
    ("¿Qué hora es?", "Son las"), ("¿Qué día es hoy?", "Hoy es"), ("Pon un temporizador de 10 minutos", "Temporizador de 10 minutos"),
    ("Avísame en 5 minutos", "Temporizador de 5 minutos"), ("Despiértame mañana a las 7", "Alarma para mañana a las 7"),
    ("Recuérdame en 20 minutos que saque la ropa", "Te lo recordaré hoy"), ("Cuánto es 23 por 47", "Son 1081"),
    ("Cuántos kilómetros son 5 millas", "5 millas son 8,05 kilómetros"), ("Pon el volumen al 70", "Volumen al 70"),
])
def test_quick_es(store, es, text, starts):
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
    assert [(i["kind"], i["label"]) for i in timers.pending() if i["kind"] != "timer"] == [
        ("reminder", "sacar la basura"), ("reminder", "llame a mamá")]


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
    monkeypatch.setattr(tools, "llm_ready", lambda name: "not on this Mac")
    assert not interpreter.enabled()  # auto, without Apple's model
    monkeypatch.setattr(tools, "llm_ready", lambda name: None)
    assert interpreter.enabled()
    settings.active["interpreter"] = "off"
    assert not interpreter.enabled()


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
    hook = load_script("jarvis-confirm")
    for name in ("set_timer", "set_alarm", "set_reminder", "cancel_timers", "set_volume"):
        assert hook.describe(f"mcp__jarvis__{name}", {}) is None


def test_spoken_durations(es):
    assert skills.spoken_duration(90) == "1 minuto y 30 segundos"
    assert skills.spoken_duration(3720) == "1 hora y 2 minutos"
    i18n.use("en")
    assert skills.spoken_duration(7205) == "2 hours"


def test_only_meant_words_stop_the_alarm(es):
    from brain.assistant import Assistant

    a = object.__new__(Assistant)
    assert a._stops_ringing("Para") and a._stops_ringing("Apaga la alarma") and a._stops_ringing("Vale")
    assert not a._stops_ringing("Kimbo.")  # its own tone, transcribed
    assert not a._stops_ringing("Gracias")
