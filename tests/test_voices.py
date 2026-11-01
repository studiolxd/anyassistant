"""The plugin «voices»: who is speaking (learning a voice, only known voices count)."""

import asyncio
import shutil
import subprocess

import numpy as np
import pytest

import kernel
import settings

kernel.load_all()
voices = kernel.load("voices")
SECOND = np.zeros(16000, np.float32)


def unit(*values):
    v = np.array(values + (0.0,) * (256 - len(values)), np.float32)
    return v / np.linalg.norm(v)


@pytest.fixture(autouse=True)
def store(tmp_path, monkeypatch):
    monkeypatch.setattr(voices, "FILE", tmp_path / "voices.json")
    monkeypatch.setattr(settings, "active", {})


class Assistant:
    """What the plugin uses of the assistant."""

    def __init__(self):
        self.said, self.shown, self.handled, self.voice, self.learning = [], [], [], None, None
        self.ear = type("Ear", (), {"wake_up": lambda self, why: True})()
        self.tasks = []

    def say(self, text):
        self.said.append(text)

    def show_heard(self, text):
        self.shown.append(text)

    def later(self, coroutine):
        self.tasks.append(coroutine)

    def run(self):
        async def all_of_them():
            while self.tasks:
                await self.tasks.pop(0)
        asyncio.run(all_of_them())

    def _state(self, state):
        pass

    def _idle_state(self):
        return "awake"


def test_nobody_known_nothing_is_checked():
    assert voices.checking() == "off"
    assert not voices.screen(Assistant(), "hola", {}, SECOND, None)


def test_judging_a_voice(monkeypatch):
    voices.learn("Suvi", [unit(1, 0)])
    voices.learn("Ana", [unit(0, 1)])
    heard = {}
    monkeypatch.setattr(voices, "voice_print", lambda audio: heard["print"])
    long, short = np.zeros(32000, np.float32), np.zeros(8000, np.float32)
    heard["print"] = unit(1, 0.2)
    assert voices.judge(long, None)[:2] == ("Suvi", True)
    heard["print"] = unit(0.3, 0.3, 1)  # someone else
    assert voices.judge(long, None)[1] is False
    heard["print"] = unit(0.4, 0.1, 1)  # «sí»: short and unclear
    assert voices.judge(short, "Suvi")[:2] == ("Suvi", True)  # whoever this conversation recognised
    assert voices.judge(short, None)[1] is False
    heard["print"] = unit(0, 1)  # short, but clearly Ana
    assert voices.judge(short, "Suvi")[:2] == ("Ana", True)


def test_only_known_voices_count(monkeypatch):
    voices.learn("Suvi", [unit(1, 0)])
    assistant = Assistant()
    handle = lambda text, timings: assistant.handled.append(text)  # noqa: E731
    monkeypatch.setattr(voices, "voice_print", lambda audio: unit(1, 0.1))
    assert voices.screen(assistant, "¿qué hora es?", {}, np.zeros(32000, np.float32), handle)
    assistant.run()
    assert assistant.handled == ["¿qué hora es?"] and assistant.voice == "Suvi"
    assert voices.who(assistant) == "(Suvi is talking.)"
    monkeypatch.setattr(voices, "voice_print", lambda audio: unit(0, 0, 1))  # a guest, the TV…
    voices.screen(assistant, "envía el correo", {}, np.zeros(32000, np.float32), handle)
    assistant.run()
    assert assistant.handled == ["¿qué hora es?"]  # dropped


def test_or_only_the_yes_to_an_action(monkeypatch, es):
    voices.learn("Suvi", [unit(1, 0)])
    settings.active["voice_check"] = "actions"
    confirmation = kernel.load("confirmation")
    answered = []
    monkeypatch.setattr(confirmation, "waiting", lambda: {"action": "send_mail"})
    monkeypatch.setattr(confirmation, "answer", lambda text: answered.append(text))
    monkeypatch.setattr(voices, "voice_print", lambda audio: unit(0, 0, 1))  # not Suvi
    assistant = Assistant()
    assert not voices.screen(assistant, "¿qué hora es?", {}, SECOND, None)  # anything else: as usual
    assert voices.screen(assistant, "Sí, adelante", {}, np.zeros(32000, np.float32), None)
    assistant.run()
    assert answered == ["no"] and assistant.said == ["No reconozco tu voz: eso no lo hago."]


def test_learning_a_voice(monkeypatch, es):
    prints = iter([unit(1, 0.1), unit(1, 0.2), unit(1, 0), unit(1, -0.1), unit(1, 0.05)])
    monkeypatch.setattr(voices, "voice_print", lambda audio: next(prints))
    assistant = Assistant()
    voices.start(assistant)
    assert assistant.said[-1] == "Vamos a aprender tu voz. ¿Cómo te llamas?"
    voices.screen(assistant, "Me llamo suvi", {}, SECOND, None)  # while learning, it takes everything
    assert assistant.said[-2].startswith("Hola, Suvi.") and assistant.said[-1].startswith("Di: ")
    voices.screen(assistant, "hoy", {}, np.zeros(8000, np.float32), None)  # too short
    assert assistant.said[-2] == "Un poco más larga: repite la frase entera."
    for _ in range(voices.PHRASES):
        voices.screen(assistant, "una frase", {}, np.zeros(32000, np.float32), None)
        assistant.run()
    assert assistant.said[-1] == "Listo, Suvi: ya conozco tu voz."
    assert [p["name"] for p in voices.people()] == ["Suvi"] and assistant.learning is None


def test_the_guide_follows_each_step(monkeypatch, es):
    """The app's and admin page's guide: the phrase to read, which one, again, done or cancelled."""
    monkeypatch.setattr(voices, "voice_print", lambda audio: unit(1, 0))
    monkeypatch.setattr(voices, "progress", {})
    assistant = Assistant()
    monkeypatch.setattr(voices.hub, "of", lambda brain: type("S", (), {"device": "mac1"})())
    voices.start(assistant)
    assert voices.progress["mac1"]["step"] == "name"
    voices.screen(assistant, "Me llamo suvi", {}, SECOND, None)
    shown = voices.progress["mac1"]
    assert (shown["step"], shown["name"], shown["number"], shown["total"]) == ("phrase", "Suvi", 1, voices.PHRASES)
    assert shown["phrase"] and assistant.said[-1] == "Di: " + shown["phrase"]
    voices.screen(assistant, "hoy", {}, np.zeros(8000, np.float32), None)  # too short
    assert voices.progress["mac1"]["again"] and voices.progress["mac1"]["number"] == 1
    voices.screen(assistant, "una frase", {}, np.zeros(32000, np.float32), None)
    assistant.run()
    assert voices.progress["mac1"]["number"] == 2 and not voices.progress["mac1"]["again"]
    assistant.learning.cancel()
    assert voices.progress["mac1"]["step"] == "cancelled" and assistant.learning is None
    assert voices._listing()["learning"]["mac1"]["step"] == "cancelled"


@pytest.mark.parametrize("said, name", [("Me llamo suvi.", "Suvi"), ("Soy Ana García", "Ana García"),
                                        ("Luis", "Luis"), ("Pues me llamo Marta", "Marta")])
def test_names(es, said, name):
    assert voices._name(said) == name


def test_the_skill_to_start_it(es):
    assistant = Assistant()
    assert voices.LearnVoice().hear("Oye, aprende mi voz", assistant)
    assert isinstance(assistant.learning, voices.Learning)
    assert not voices.LearnVoice().hear("¿Qué hora es?", Assistant())


def say(tmp_path, voice, text):
    import soundfile

    aiff, wav = tmp_path / "a.aiff", tmp_path / "a.wav"
    subprocess.run(["say", "-v", voice, "-o", str(aiff), text], check=True)
    subprocess.run(["afconvert", "-f", "WAVE", "-d", "LEI16@16000", "-c", "1", str(aiff), str(wav)], check=True)
    return soundfile.read(wav, dtype="float32")[0]


def _model_here() -> bool:
    try:
        from huggingface_hub import try_to_load_from_cache

        return isinstance(try_to_load_from_cache(*voices.MODEL), str)
    except Exception:
        return False


@pytest.mark.skipif(not shutil.which("say") or not _model_here(), reason="needs macOS voices and the model")
def test_the_real_model_tells_two_voices_apart(tmp_path):
    sentences = ["Hoy hace un buen día para salir a pasear.", "Pon una alarma mañana a las siete y media.",
                 "Recuérdame que tengo que llamar a mi madre."]
    voices.learn("Mónica", [voices.voice_print(say(tmp_path, "Mónica", s)) for s in sentences])
    assert voices.identify(say(tmp_path, "Mónica", "Envía el correo a Ana, por favor."))[1] > 0.6
    assert voices.identify(say(tmp_path, "Paulina", "Envía el correo a Ana, por favor."))[1] < 0.5


def test_a_print_per_device_for_the_same_person(monkeypatch):
    """Learnt on the Mac and then on the iPhone: one person, two prints; each microphone matches its own."""
    voices.learn("Suvi", [unit(1, 0)], device="mac")
    voices.learn("suvi", [unit(0, 1)], device="iphone")  # the same person (any case)
    assert [p["name"] for p in voices.people()] == ["Suvi"] and voices._listing()["people"][0]["devices"] == 2
    monkeypatch.setattr(voices, "voice_print", lambda audio: unit(0.05, 1))  # through the iPhone
    assert voices.identify(SECOND) == ("Suvi", pytest.approx(1, abs=0.01))
    voices.learn("Suvi", [unit(1, 0.1)], device="mac")  # the Mac's again: replaced, not added
    assert voices._listing()["people"][0]["devices"] == 2


def test_an_old_single_print_is_kept(monkeypatch):
    voices._save([{"name": "Ana", "print": [float(x) for x in unit(1, 0)], "samples": 5, "since": 0}])
    monkeypatch.setattr(voices, "voice_print", lambda audio: unit(1, 0))
    assert voices.identify(SECOND)[0] == "Ana"
    voices.learn("Ana", [unit(0, 1)], device="iphone")
    assert voices._listing()["people"][0]["devices"] == 2  # the old one stays, the iPhone's added
