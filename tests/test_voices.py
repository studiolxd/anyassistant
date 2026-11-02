"""The plugin «voices»: who is speaking (learning a voice, only known voices count)."""

import asyncio
import json
import time
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


@pytest.mark.parametrize("said", ["Apréndeme voz.", "apréndete mi voz", "registra mi vos",
                                  "Entrena mi voz.", "entréname la voz", "Oye, entrena una voz"])
def test_the_skill_to_start_it_as_transcribed(es, said):
    assert voices.LearnVoice().hear(said, Assistant())


def test_a_longer_sentence_about_voices_isnt_it(es):
    assert not voices.LearnVoice().hear("aprendí a cambiar la voz del asistente ayer por la tarde", Assistant())


def test_repeating_what_it_said_while_learning_isnt_its_echo(monkeypatch):
    """Learning a voice, you repeat its «Di: …»: not dropped as its echo by its words."""
    from plugins.brain_assistant import Assistant as Brain

    a = object.__new__(Brain)
    a.said, a.saying = [], "di hoy hace un buen día para salir a pasear por el parque".split()
    seen = []
    monkeypatch.setattr(Brain, "_talked_over", lambda self: None)
    monkeypatch.setattr(kernel, "module", lambda name: None)
    monkeypatch.setattr(Brain, "_handle", lambda self, text, timings: seen.append(text))
    a.learning = object()
    a._heard("Hoy hace un buen día para salir a pasear por el parque.", {"over": True, "stt_ms": 100, "audio_s": 3})
    assert seen  # heard, not dropped


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


def test_only_a_known_voice_wakes_it(monkeypatch):
    """«Ey, Eva» by a stranger doesn't wake it once someone is known (voice_check all)."""
    assert voices.may_wake(SECOND)  # nobody known: anyone
    voices.learn("Suvi", [unit(1, 0)], device="mac")
    monkeypatch.setattr(voices, "voice_print", lambda audio: unit(1, 0.6))  # Suvi, quickly: 0.86
    assert voices.may_wake(SECOND)
    monkeypatch.setattr(voices, "voice_print", lambda audio: unit(1, 2))  # Suvi far away: ~0.45, not refused
    assert voices.may_wake(SECOND)
    monkeypatch.setattr(voices, "voice_print", lambda audio: unit(0, 0, 1))  # a guest
    assert not voices.may_wake(SECOND)
    settings.active["voice_check"] = "actions"  # only the «yes» needs a known voice: anyone wakes it
    assert voices.may_wake(SECOND)


def test_harmless_commands_need_only_a_voice_not_clearly_a_strangers(monkeypatch, es):
    """«Apágate», «para», the time are harmless (and short: their print says less): as «Ey, Eva», only a
    voice clearly unlike everyone is refused."""
    voices.learn("Suvi", [unit(1, 0)])
    settings.active["voice_check"] = "all"
    long = np.zeros(24000, np.float32)  # 1.5 s: too long for «short, as whoever was talking»
    monkeypatch.setattr(voices, "voice_print", lambda audio: unit(1, 2))  # Suvi, quickly: ~0.45
    assert not voices.screen(Assistant(), "Apágate.", {}, long, None)  # handled as usual: it sleeps
    assert not voices.screen(Assistant(), "¿Qué hora es?", {}, long, None)  # the time: as usual
    assert not voices.screen(Assistant(), "Para.", {}, long, None)
    assert voices.screen(Assistant(), "Envía el correo a Ana.", {}, long, lambda *a: None)  # anything else: checked
    monkeypatch.setattr(voices, "voice_print", lambda audio: unit(0, 0, 1))  # a guest
    assistant = Assistant()
    assert voices.screen(assistant, "Apágate.", {}, long, lambda *a: None)  # checked, and dropped
    assert voices.screen(assistant, "¿Qué hora es?", {}, long, lambda *a: None)
    assert not assistant.tasks  # dropped at once, nothing asked


def test_a_sentence_in_the_unclear_band_asks_before_doing_it(monkeypatch, es, project):
    """Between the lower bound and voice_match, something that would do something isn't dropped: it asks
    «¿lo hago?» and does it on a «yes» from a recognised voice."""
    voices.learn("Suvi", [unit(1, 0)])
    settings.active["voice_check"] = "all"
    confirmation = kernel.load("confirmation")
    assistant = Assistant()
    handled = []
    handle = lambda text, timings: handled.append(text)  # noqa: E731
    long = np.zeros(32000, np.float32)
    monkeypatch.setattr(voices, "voice_print", lambda audio: unit(1, 2))  # Suvi, far: ~0.45
    assert voices.screen(assistant, "Envía el correo a Ana.", {"audio_s": 2}, long, handle)
    assistant.run()
    assert handled == [] and assistant.said == ["No he reconocido bien tu voz: ¿lo hago?"]
    assert assistant.shown == ["Envía el correo a Ana."] and confirmation.waiting()["consume"]
    assert assistant.unclear["text"] == "Envía el correo a Ana."
    monkeypatch.setattr(voices, "voice_print", lambda audio: unit(1, 0.1))  # the «yes», clearly Suvi
    assert voices.screen(assistant, "Sí, hazlo.", {}, long, handle)
    assistant.run()
    assert handled == ["Envía el correo a Ana."] and assistant.voice == "Suvi" and assistant.unclear is None
    assert confirmation.waiting() is None and assistant.shown[-1] == "Sí, hazlo."


def test_anything_but_yes_cancels_it_and_a_stranger_is_still_dropped(monkeypatch, es, project):
    voices.learn("Suvi", [unit(1, 0)])
    settings.active["voice_check"] = "all"
    confirmation = kernel.load("confirmation")
    assistant = Assistant()
    handled = []
    handle = lambda text, timings: handled.append(text)  # noqa: E731
    long = np.zeros(32000, np.float32)
    monkeypatch.setattr(voices, "voice_print", lambda audio: unit(0, 0, 1))  # clearly nobody known: dropped
    assert voices.screen(assistant, "Envía el correo a Ana.", {}, long, handle)
    assistant.run()
    assert not assistant.said and confirmation.waiting() is None
    monkeypatch.setattr(voices, "voice_print", lambda audio: unit(1, 2))  # not clear: it asks
    voices.screen(assistant, "Borra la lista de la compra.", {}, long, handle)
    assistant.run()
    assert assistant.said == ["No he reconocido bien tu voz: ¿lo hago?"]
    monkeypatch.setattr(voices, "voice_print", lambda audio: unit(1, 0.1))
    voices.screen(assistant, "No, déjalo.", {}, long, handle)
    assistant.run()
    assert handled == [] and confirmation.waiting() is None and assistant.unclear is None
    voices.screen(assistant, "Envía un mensaje a la cocina.", {}, long, handle)  # nothing waits: as usual
    assistant.run()
    assert handled == ["Envía un mensaje a la cocina."]


def test_a_short_unclear_yes_doesnt_count_and_a_second_question_isnt_stacked(monkeypatch, es, project):
    voices.learn("Suvi", [unit(1, 0)])
    settings.active["voice_check"] = "all"
    confirmation = kernel.load("confirmation")
    assistant = Assistant()
    handled = []
    handle = lambda text, timings: handled.append(text)  # noqa: E731
    long = np.zeros(32000, np.float32)
    monkeypatch.setattr(voices, "voice_print", lambda audio: unit(1, 2))
    voices.screen(assistant, "Envía el correo a Ana.", {}, long, handle)
    assistant.run()
    voices.screen(assistant, "Llama a mi madre.", {}, long, handle)  # another unclear one: dropped, not asked again
    assistant.run()
    assert assistant.said == ["No he reconocido bien tu voz: ¿lo hago?"]
    voices.screen(assistant, "Sí.", {}, np.zeros(8000, np.float32), handle)  # short and unclear: nobody recognised yet
    assistant.run()
    assert handled == [] and confirmation.waiting()  # still waiting
    assistant.voice = "Suvi"  # once the conversation knows who talks, a short «sí» counts as them
    voices.screen(assistant, "Sí.", {}, np.zeros(8000, np.float32), handle)
    assistant.run()
    assert handled == ["Envía el correo a Ana."]


def test_with_a_tool_waiting_for_a_yes_an_unclear_voice_is_dropped(monkeypatch, es, project):
    voices.learn("Suvi", [unit(1, 0)])
    settings.active["voice_check"] = "all"
    confirmation = kernel.load("confirmation")
    confirmation.store.ask("abc", "anyassistant: send_mail")
    assistant = Assistant()
    long = np.zeros(32000, np.float32)
    monkeypatch.setattr(voices, "voice_print", lambda audio: unit(1, 2))
    voices.screen(assistant, "Sí, envíalo.", {}, long, lambda *a: None)
    assistant.run()
    assert not assistant.said and confirmation.waiting()["signature"] == "abc"


def test_it_warns_once_when_someones_score_drops_on_a_device(monkeypatch, es):
    """Their usual score per device: when the recent ones stay ~0.15 below, a notice, once."""
    voices.learn("Suvi", [unit(1, 0)], device="ipad")
    told = []

    class Notices:
        async def tell(self, text):
            told.append(text)

    devices = kernel.load("devices")
    monkeypatch.setattr(voices, "kernel_module", lambda name: {"notices": Notices(), "devices": devices}[name])
    monkeypatch.setattr(devices, "describe", lambda device: "iPad (cocina)" if device == "ipad" else "?")
    assistant = Assistant()
    for _ in range(12):
        voices.track(assistant, "Suvi", "ipad", 0.78)
    assistant.run()
    assert not told
    for _ in range(2):  # a couple of bad ones: not yet
        voices.track(assistant, "Suvi", "ipad", 0.6)
    assistant.run()
    assert not told
    voices.track(assistant, "Suvi", "ipad", 0.6)  # most of the last five: it stays low
    assistant.run()
    assert told == ["Suvi: conviene volver a aprender tu voz en iPad (cocina)."]
    assert voices._listing()["people"][0]["relearn"] == ["iPad (cocina)"]
    for _ in range(5):  # it goes on: not again
        voices.track(assistant, "Suvi", "ipad", 0.58)
    assistant.run()
    assert len(told) == 1
    for _ in range(5):  # back to usual: the warning goes, and some day it may warn again
        voices.track(assistant, "Suvi", "ipad", 0.8)
    assert voices._listing()["people"][0]["relearn"] == []
    assert len(voices.people()[0]["usual"]["ipad"]["scores"]) <= voices.USUAL


def test_learning_the_voice_again_there_clears_the_warning(monkeypatch):
    voices.learn("Suvi", [unit(1, 0)], device="ipad")
    monkeypatch.setattr(voices, "kernel_module", lambda name: None)
    assistant = Assistant()
    for _ in range(12):
        voices.track(assistant, "Suvi", "ipad", 0.78)
    for _ in range(5):
        voices.track(assistant, "Suvi", "ipad", 0.55)
    assert voices.people()[0]["usual"]["ipad"]["warned"] and voices.relearn(voices.people()[0]) == ["ipad"]
    voices.learn("Suvi", [unit(1, 0.1)], device="mac")  # another device: the iPad's warning stays
    assert voices.relearn(voices.people()[0]) == ["ipad"]
    voices.learn("Suvi", [unit(1, 0.1)], device="ipad")
    assert voices.relearn(voices.people()[0]) == [] and "ipad" not in voices.people()[0]["usual"]


def test_only_long_accepted_sentences_count_for_the_usual_score(monkeypatch):
    voices.learn("Suvi", [unit(1, 0)], device="ipad")
    monkeypatch.setattr(voices.hub, "of", lambda brain: type("S", (), {"device": "ipad"})())
    assistant = Assistant()
    monkeypatch.setattr(voices, "voice_print", lambda audio: unit(1, 0.3))  # 0.96
    voices.screen(assistant, "¿Qué tengo en la agenda para mañana?", {}, np.zeros(32000, np.float32), lambda *a: None)
    assistant.run()
    assert voices.people()[0]["usual"]["ipad"]["scores"] == [0.958]
    assistant.voice = "Suvi"
    monkeypatch.setattr(voices, "voice_print", lambda audio: unit(1, 2))  # a short «sí», as Suvi: says nothing
    voices.screen(assistant, "Sí.", {}, np.zeros(8000, np.float32), lambda *a: None)
    assistant.run()
    assert len(voices.people()[0]["usual"]["ipad"]["scores"]) == 1


def test_it_keeps_learning_a_voice_from_what_it_is_sure_of(monkeypatch):
    """voice_adapt: long sentences clearly theirs make a recent print, which brings them nearer."""
    voices.learn("Suvi", [unit(1, 0)], device="mac")
    long = np.zeros(int(2.5 * 16000), np.float32)
    everyday = unit(1, 0.9)  # how Suvi really talks: 0.74 to the learnt print
    monkeypatch.setattr(voices, "voice_print", lambda audio: everyday)
    assert voices.identify(long)[1] < 0.75
    voices.adapt(long, "Suvi")
    assert voices.identify(long)[1] > 0.99  # the recent print is just like it
    voices.adapt(np.zeros(16000, np.float32), "Suvi")  # too short: not kept
    assert len(voices.people()[0]["recent"]) == 1
    for _ in range(15):
        voices.adapt(long, "Suvi")
    assert len(voices.people()[0]["recent"]) == voices.RECENT  # only the last ones
    voices.learn("Suvi", [unit(0, 1)], device="iphone")  # another device: its own last ones
    monkeypatch.setattr(voices, "voice_print", lambda audio: unit(0.1, 1))  # as the iPhone hears her
    for _ in range(3):
        voices.adapt(long, "Suvi")
    near = [r["near"] for r in voices.people()[0]["recent"]]
    assert near.count("mac") == voices.RECENT and near.count("iphone") == 3


def test_a_recent_print_cant_drift_to_someone_else(monkeypatch):
    voices.learn("Suvi", [unit(1, 0)], device="mac")
    long = np.zeros(int(2.5 * 16000), np.float32)
    monkeypatch.setattr(voices, "voice_print", lambda audio: unit(1, 0.9))
    voices.adapt(long, "Suvi")
    monkeypatch.setattr(voices, "voice_print", lambda audio: unit(0.3, 1))  # far from the learnt one
    assert voices.identify(long)[1] < 0.5  # its recent print doesn't let it in
    monkeypatch.setattr(voices, "voice_print", lambda audio: unit(1, 3))  # 0.32: not sure, not kept
    voices.adapt(long, "Suvi")
    assert len(voices.people()[0]["recent"]) == 1


def test_off_it_deletes_what_it_learnt_that_way(monkeypatch):
    voices.learn("Suvi", [unit(1, 0)], device="mac")
    long = np.zeros(int(2.5 * 16000), np.float32)
    monkeypatch.setattr(voices, "voice_print", lambda audio: unit(1, 0.9))
    voices.adapt(long, "Suvi")
    settings.active["voice_adapt"] = False
    assert voices.identify(long)[1] < 0.75  # not used
    voices.adapt(long, "Suvi")
    voices.drop_recent()
    assert "recent" not in voices.people()[0]
    settings.active["voice_adapt"] = True
    voices.adapt(long, "Suvi")
    voices.learn("Suvi", [unit(1, 0)], device="mac")  # learnt again on that device: its recent ones go
    assert voices.people()[0]["recent"] == []


class Session:
    """A connected device, as hub keeps it."""

    def __init__(self, device, remote, brain):
        self.id, self.device, self.remote, self.brain = device, device, remote, brain
        self.pc = type("PC", (), {"connectionState": "connected"})()


def test_the_installer_registers_the_voice_on_this_computer(monkeypatch, tmp_path, es):
    """The installer's «Your voice» (a device step), through /setup/device/voice: started on this
    computer's own device (not a tablet), followed, cancelled."""
    import sys

    import hub
    import installer
    import web
    from test_admin_web import request

    voices = sys.modules[installer.STEPS["voice"].function.__module__]  # the plugin as loaded last
    monkeypatch.setattr(voices, "FILE", tmp_path / "voices.json")
    monkeypatch.setattr(voices, "progress", {})
    here, tablet = Assistant(), Assistant()
    monkeypatch.setattr(hub, "sessions", {"mac1": Session("mac1", "127.0.0.1", here),
                                          "tab1": Session("tab1", "192.168.1.40", tablet)})

    def call(method="GET", body=None, remote="127.0.0.1"):
        made = request(method, "/setup/device/voice", remote=remote, body=body)
        made.match_info["step"] = "voice"
        answer = asyncio.run(web.setup_device(made))
        return answer.status, json.loads(answer.body)

    assert call() == (200, {"device": "mac1", "state": None})  # not started yet
    assert call(remote="192.168.1.40")[0] == 403  # only this computer (or an admin)
    status, answer = call("POST", {"do": "start"})
    assert status == 200 and isinstance(here.learning, voices.Learning) and tablet.learning is None
    assert answer["state"] == {"state": "running", "title": "Di tu nombre", "text": "",
                               "detail": "En voz alta, por ejemplo: «Me llamo Ana».", "fraction": 0}
    monkeypatch.setattr(voices, "voice_print", lambda audio: unit(1, 0))
    voices.screen(here, "Me llamo suvi", {}, SECOND, None)
    state = call()[1]["state"]
    assert state["title"] == f"Frase 1 de {voices.PHRASES}" and state["text"] == voices.progress["mac1"]["phrase"]
    assert state["detail"] == "Léela en voz alta."
    voices.screen(here, "una frase", {}, np.zeros(32000, np.float32), None)
    here.run()
    assert call()[1]["state"]["fraction"] == 1 / voices.PHRASES
    status, answer = call("POST", {"do": "cancel"})
    assert answer["state"] == {"state": "cancelled", "title": "", "text": "No se ha aprendido nada.", "detail": "",
                               "fraction": None}
    call("POST", {"do": "start"})
    voices.screen(here, "Soy Suvi", {}, SECOND, None)
    for _ in range(voices.PHRASES):
        voices.screen(here, "una frase", {}, np.zeros(32000, np.float32), None)
        here.run()
    assert call()[1]["state"]["state"] == "done" and call()[1]["state"]["text"] == "Ya conoce tu voz, Suvi."
    assert [p["name"] for p in voices.people()] == ["Suvi"]


def test_no_device_on_this_computer_yet(monkeypatch):
    import hub
    import web
    from test_admin_web import request

    monkeypatch.setattr(hub, "sessions", {"tab1": Session("tab1", "192.168.1.40", Assistant())})
    made = request("POST", "/setup/device/voice", remote="127.0.0.1", body={"do": "start"})
    made.match_info["step"] = "voice"
    answer = asyncio.run(web.setup_device(made))
    assert answer.status == 409
    made = request("GET", "/setup/device/nothing", remote="127.0.0.1")
    made.match_info["step"] = "nothing"
    assert asyncio.run(web.setup_device(made)).status == 404


def test_forgetting_a_voice_keeps_or_deletes_what_it_remembers_of_them(tmp_path, monkeypatch):
    """Settings → Known voices: «Conservar» keeps their facts under their name; «Borrar» deletes them too."""
    from aiohttp.test_utils import make_mocked_request
    memory = kernel.load("memory")
    monkeypatch.setattr(memory, "PATH", tmp_path / "memory.json")
    monkeypatch.setattr(kernel, "module", lambda plugin: memory if plugin == "memory" else None)
    (tmp_path / "memory.json").write_text(json.dumps({"facts": ["The wifi is called Casa."],
                                                      "people": {"Suvi": ["Invoices with Holded."]}}))
    for name in ("Suvi", "Ana"):
        voices.learn(name, [unit(1.0)])

    def post(body):
        request = make_mocked_request("POST", "/admin/voices", transport=type("T", (), {
            "get_extra_info": lambda self, k, d=None: ("127.0.0.1", 1) if k == "peername" else d})())
        request.json = lambda: asyncio.sleep(0, body)
        return json.loads(asyncio.run(voices._change(request)).body)

    listed = {p["name"]: p["facts"] for p in post({})["people"]}
    assert listed == {"Suvi": 1, "Ana": 0}  # the app asks only when there is something
    post({"forget": "Ana"})
    assert memory.load()["people"] == {"Suvi": ["Invoices with Holded."]}
    voices.learn("Ana", [unit(1.0)])
    post({"forget": "Suvi", "memory": "keep"})
    assert memory.load()["people"] == {"Suvi": ["Invoices with Holded."]}  # as before: kept under the name
    voices.learn("Suvi", [unit(1.0)])
    answer = post({"forget": "Suvi", "memory": "delete"})
    assert [p["name"] for p in answer["people"]] == ["Ana"]
    assert memory.load()["people"] == {} and memory.load()["facts"] == ["The wifi is called Casa."]


def test_renaming_a_voice_and_merging_it_with_one_of_that_name(tmp_path, monkeypatch):
    """«Subi» (as transcribed) → «Suvi»; if «Suvi» is known already, one voice: prints and memories together."""
    memory = kernel.load("memory")
    monkeypatch.setattr(memory, "PATH", tmp_path / "memory.json")
    (tmp_path / "memory.json").write_text(json.dumps({"facts": [], "people": {"Subi": ["Has a dog, Toby."]}}))
    voices.learn("Subi", [unit(1.0)], "tablet")
    assert voices.rename("Subi", "Suvi") and [p["name"] for p in voices.people()] == ["Suvi"]
    memory.rename_person("Subi", "Suvi")
    assert memory.load()["people"] == {"Suvi": ["Has a dog, Toby."]}

    voices.learn("Ana", [unit(0, 1.0)], "tablet")
    voices.learn("Ana", [unit(0, 0, 1.0)], "mac")
    (tmp_path / "memory.json").write_text(json.dumps({"facts": [], "people": {"Suvi": ["Has a dog, Toby."],
                                                                              "Ana": ["Likes jazz.", "Has a dog, Toby."]}}))
    assert voices.rename("Ana", "suvi")  # another name it knows: merged
    merged = voices.people()
    assert [p["name"] for p in merged] == ["suvi"] and set(merged[0]["prints"]) == {"tablet", "mac"}
    assert np.allclose(np.linalg.norm(merged[0]["prints"]["tablet"]), 1)  # the same device in both: averaged
    memory.rename_person("Ana", "suvi")
    assert memory.load()["people"] == {"suvi": ["Has a dog, Toby.", "Likes jazz."]}
    assert not voices.rename("Nobody", "X") and not voices.rename("suvi", " ")


def test_the_skill_in_english(en):
    assert voices.LearnVoice().hear("Train my voice", Assistant())


def test_each_device_lists_the_voices_learnt_there(monkeypatch):
    monkeypatch.setattr(time, "time", lambda: 1000.0)
    voices.learn("Suvi", [unit(1, 0)], device="mac")
    voices.learn("Suvi", [unit(0, 1)], device="iphone")
    voices.learn("Ana", [unit(0, 1)], device="iphone")
    assert voices.on("iphone") == [{"name": "Suvi", "learnt": 1000.0}, {"name": "Ana", "learnt": 1000.0}]
    assert voices.on("mac") == [{"name": "Suvi", "learnt": 1000.0}] and voices.on("watch") == []


def test_forgetting_a_voice_on_one_device(monkeypatch):
    voices.learn("Suvi", [unit(1, 0)], device="mac")
    voices.learn("Suvi", [unit(0, 1)], device="iphone")
    assert voices.forget("suvi", "iphone")
    assert voices.on("iphone") == [] and [p["name"] for p in voices.people()] == ["Suvi"]  # still known on the Mac
    assert not voices.forget("Suvi", "iphone")  # nothing there any more
    assert voices.forget("Suvi", "mac") and voices.people() == []  # its last one: forgotten

