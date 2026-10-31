"""Plan B (llm-fallback), always on, lists and notes, the weather (without the network)."""

import asyncio

import pytest

import kernel
import llm
import settings
from skills.tokens import tokens


# --- Plan B ---

class Failing(llm.LLM):
    name = "claude"

    async def answer(self, text, image=None):
        raise llm.Unavailable("Perdona, se me ha cortado la conexión con Claude.")
        yield  # an async generator


class Local(llm.LLM):
    name = "apple"

    async def answer(self, text, image=None):
        yield "Son las ocho."


def pieces(assistant, monkeypatch, backup):
    from plugins.brain_assistant import Assistant

    monkeypatch.setattr(kernel.load("llm-fallback"), "instead", lambda current: backup)
    fake = Assistant.__new__(Assistant)
    fake.llm = Failing()

    async def collect():
        return "".join([p async for p in Assistant._pieces(fake, "¿Qué hora es?", None)])
    return asyncio.run(collect())


def test_plan_b_answers_saying_so(monkeypatch, es):
    said = pieces(None, monkeypatch, Local())
    assert said.startswith("Claude no responde") and said.endswith("Son las ocho.")


def test_without_plan_b_it_says_why(monkeypatch, es):
    assert pieces(None, monkeypatch, None) == "Perdona, se me ha cortado la conexión con Claude."


def test_plan_b_chooses_a_local_one_not_itself(monkeypatch):
    fallback = kernel.load("llm-fallback")
    monkeypatch.setattr(llm, "available", lambda: ["apple", "claude"])
    monkeypatch.setattr(llm, "ready", lambda name: None)
    monkeypatch.setattr(settings, "active", {})
    assert fallback.chosen("claude") == "apple" and fallback.chosen("apple") is None
    monkeypatch.setattr(settings, "active", {"llm_fallback": "none"})
    assert fallback.chosen("claude") is None


# --- Always on ---

def test_always_on_starts_awake_and_doesnt_sleep_by_itself(monkeypatch):
    from plugins.brain_transcriber.ear import Ear

    class Wake:
        phrase = "Hey Jarvis"

    assert not Ear(None, lambda s: None, lambda *a: None, wake=Wake()).awake
    monkeypatch.setattr(settings, "active", {"plugins": {"always-on": True}})
    assert Ear(None, lambda s: None, lambda *a: None, wake=Wake()).awake


# --- Lists and notes ---

@pytest.fixture
def lists(tmp_path, monkeypatch, es):
    module = kernel.load("skill-lists")
    monkeypatch.setattr(module, "PATH", tmp_path / "lists.json")
    skill = module.Lists()
    return lambda text: skill.answer(text, tokens(text))


def test_a_shopping_list_by_voice(lists):
    assert lists("Añade leche, huevos y plátanos a la lista de la compra") == \
        "Apuntado en la lista de la compra: leche, huevos y plátanos."
    assert lists("Apunta leche en la lista") == "Ya estaba en la lista de la compra."
    assert lists("Quita los huevos de la lista de la compra") == "Quitado de la lista de la compra: huevos."
    assert lists("¿Qué hay en la lista?") == "En la lista de la compra hay leche y plátanos."
    assert lists("Vacía la lista de la compra") == "He vaciado la lista de la compra."
    assert lists("Pon regalo para Ana en la lista de cumpleaños") == "Apuntado en la lista de cumpleaños: regalo para Ana."


def test_notes(lists):
    assert lists("¿Qué notas tengo?") == "No tienes notas."
    assert lists("Toma nota de que el fontanero viene el jueves") == "Anotado."
    assert lists("¿Qué notas tengo?") == "Tienes una nota: el fontanero viene el jueves."
    assert lists("Borra las notas") == "He borrado las notas."


def test_not_everything_with_add_is_a_list(lists):
    assert lists("Pon un temporizador de 5 minutos") is None
    assert lists("Añade un recordatorio") is None


# --- Weather ---

def test_weather_questions(es):
    weather = kernel.load("skill-weather")
    assert weather.understood("¿Qué tiempo hace?") == {"day": 0, "rain": False, "city": None}
    assert weather.understood("¿Va a llover mañana?") == {"day": 1, "rain": True, "city": None}
    assert weather.understood("¿Qué tiempo hará pasado mañana en Málaga?") == {"day": 2, "rain": False, "city": "Málaga"}
    assert weather.understood("¿Cuánto tiempo queda?") is None


def test_weather_sentence(es):
    weather = kernel.load("skill-weather")
    data = {"current": {"temperature_2m": 18.4, "weather_code": 2},
            "daily": {"temperature_2m_min": [15.2, 11, 9], "temperature_2m_max": [19.6, 21, 20],
                      "precipitation_probability_max": [93, 0, 40], "weather_code": [80, 0, 61]}}
    assert weather.said(data, "Valencia", 0, False) == ("Ahora en Valencia hace 18 grados, parcialmente nublado. Hoy, "
                                                        "entre 15 y 20 grados, con chubascos, con un 93 % de "
                                                        "probabilidad de lluvia.")
    assert weather.said(data, "Valencia", 1, True) == "Mañana no parece que vaya a llover en Valencia: un 0 %."
    assert weather.said(data, "Valencia", 2, True) == "Pasado mañana puede que llueva en Valencia: un 40 %."


def test_without_a_city_it_asks_for_one(es, monkeypatch):
    monkeypatch.setattr(settings, "active", {})
    assert "ciudad" in kernel.load("skill-weather").answer()


def test_an_alarm_rings_until_stopped_with_zero():
    from plugins.brain_assistant import RING_MAX, ring_for

    assert ring_for(None) == 60 and ring_for(45) == 45
    assert ring_for(0) == RING_MAX == 30 * 60  # «until someone stops it», but not forever
    assert ring_for(10_000) == RING_MAX
