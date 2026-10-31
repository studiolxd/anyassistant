"""Several devices at once (hub.py, the plugin «devices»): a device that reconnects replaces
itself, one conversation at a time, and when two hear the same «Jarvis» only the louder answers."""

import numpy as np
import pytest

import hub
import kernel
import paths
import vad

kernel.load_all()  # plugins.* importable
from plugins.brain_transcriber import Transcriber
from plugins import devices


class Wake:
    phrase = "Hey Jarvis"
    continuous = False
    heard_sentence = None

    def __init__(self):
        self.hears = False

    def listen(self, audio):
        return self.hears

    def reset(self):
        self.hears = False


class Speaker:
    speaking = False
    last_sound = 0.0

    def play(self, pcm):
        pass


class Silence:
    """No real VAD (it would load torch): nobody speaks here."""

    def probability(self, window):
        return 0.0

    def reset(self):
        pass


class Connection:
    connectionState = "connected"


class Session:
    def __init__(self, id, device=None, agent=""):
        self.id, self.device, self.agent = id, device, agent
        self.pc = Connection()
        self.sent = []
        self.brain = Transcriber(stt=None, wake=Wake(), speaker=Speaker(), send=self.sent.append)

    def send(self, message):
        self.sent.append(message)


@pytest.fixture(autouse=True)
def empty(monkeypatch, tmp_path):
    monkeypatch.setattr(hub, "sessions", {})
    monkeypatch.setattr(hub, "active", None)
    monkeypatch.setattr(hub, "_claim", None)
    monkeypatch.setattr(devices, "FILE", tmp_path / "devices.json")
    monkeypatch.setattr(paths, "HOME", tmp_path)
    monkeypatch.setattr(vad, "create", Silence)


def connect(id, device=None, agent=""):
    session = Session(id, device, agent)
    hub.add(session)
    return session


def hears_its_name(session, loudness):
    """A chunk of its name at this loudness (20 ms at 48 kHz)."""
    session.brain.wake.hears = True
    session.brain.hear(np.full(960, int(loudness * 32767), np.int16))


def test_a_device_that_reconnects_replaces_its_old_connection():
    first = connect("a", "tablet")
    connect("b", "ipad")
    old = hub.add(Session("c", "tablet"))
    assert old == [first]
    assert [s.id for s in hub.all()] == ["b", "c"]


def test_the_current_one_is_the_one_that_woke_up():
    kitchen, living = connect("a", "kitchen"), connect("b", "living")
    assert hub.current() is living  # none woke yet: the last one connected
    hears_its_name(kitchen, 0.3)
    assert kitchen.brain.ear.awake and hub.current() is kitchen


def test_two_hear_the_same_word_the_louder_answers():
    near, far = connect("a", "near"), connect("b", "far")
    hears_its_name(far, 0.05)  # it heard it first, faintly
    assert far.brain.ear.awake
    hears_its_name(near, 0.4)  # the same word, louder, a moment later
    assert near.brain.ear.awake and not far.brain.ear.awake
    assert hub.current() is near
    assert {"type": "state", "state": "asleep", "wake_phrase": "Hey Jarvis"} in far.sent


def test_the_fainter_one_after_doesnt_wake():
    near, far = connect("a", "near"), connect("b", "far")
    hears_its_name(near, 0.4)
    hears_its_name(far, 0.05)
    assert near.brain.ear.awake and not far.brain.ear.awake


def test_one_conversation_at_a_time(monkeypatch):
    kitchen, living = connect("a", "kitchen"), connect("b", "living")
    hears_its_name(kitchen, 0.3)
    monkeypatch.setattr(hub, "_claim", None)  # a while later: another word, elsewhere
    hears_its_name(living, 0.3)
    assert living.brain.ear.awake and not kitchen.brain.ear.awake


def test_its_voice_saying_its_name_doesnt_wake_another():
    talking, nearby = connect("a", "talking"), connect("b", "nearby")
    hears_its_name(talking, 0.3)
    talking.brain.ear.deaf = lambda: True  # speaking: «… I'm Jarvis …»
    hears_its_name(nearby, 0.5)
    assert not nearby.brain.ear.awake and talking.brain.ear.awake


def test_devices_get_a_name_and_a_room(monkeypatch):
    first = connect("a", "x1", "Mozilla/5.0 (iPad; CPU OS 18_0 like Mac OS X)")
    second = connect("b", "x2", "Mozilla/5.0 (iPad; CPU OS 17_0 like Mac OS X)")
    devices._connected(first)
    devices._connected(second)
    assert [d["name"] for d in devices.load().values()] == ["iPad", "iPad 2"]
    monkeypatch.setattr(hub, "active", "a")
    devices.set_device(room="cocina")
    assert devices.describe("x1") == "iPad (cocina)"
    assert "you're talking through this one" in devices.get_devices()
    with pytest.raises(devices.ToolError):
        devices.set_device(name="iPad 2")  # the other one's


# --- Where timers, alarms and reminders ring ---

from plugins import skill_alarms as alarms  # noqa: E402
from plugins.skill_alarms import timers  # noqa: E402
import settings  # noqa: E402
import skills  # noqa: E402


class Ringer(Session):
    """A device whose brain rings (as the assistant's does)."""

    def __init__(self, *args):
        super().__init__(*args)
        self.brain.ring = lambda item: None


@pytest.fixture
def house(tmp_path, monkeypatch):
    monkeypatch.setattr(timers, "PATH", tmp_path / "timers.json")
    monkeypatch.setattr(settings, "active", {})
    kitchen, bedroom = Ringer("a", "k1"), Ringer("b", "b1")
    for session in (kitchen, bedroom):
        hub.add(session)
    devices._save({"k1": {"name": "tablet", "room": "cocina"}, "b1": {"name": "iPad", "room": "dormitorio"}})
    monkeypatch.setattr(hub, "active", "b")  # you're talking to the bedroom's
    return kitchen, bedroom


def test_it_rings_where_it_was_set(house, es):
    kitchen, bedroom = house
    skills.quick("Pon una alarma a las 7")
    assert alarms.targets(timers.pending()[0]) == [bedroom]


def test_everywhere_by_the_option(house, es):
    settings.active["alarm_rings"] = "everywhere"
    skills.quick("Pon un temporizador de 10 minutos")
    assert alarms.targets(timers.pending()[0]) == list(house)


@pytest.mark.parametrize("text, where", [
    ("Pon una alarma a las 7 en todos", "all"),
    ("Pon un temporizador de 5 minutos en toda la casa", "all"),
    ("Pon una alarma a las 8 en todos los dispositivos", "all"),
    ("Pon un temporizador de 10 minutos en la cocina", "cocina"),
])
def test_where_by_voice(house, es, text, where):
    answer = skills.quick(text)
    item = timers.pending()[0]
    assert item["where"] == where and answer.endswith("Sonará en todos." if where == "all" else "Sonará en la cocina.")
    assert alarms.targets(item) == (list(house) if where == "all" else [house[0]])


def test_a_reminder_with_where_keeps_its_text(house, es):
    skills.quick("Recuérdame en la cocina a las 9 que saque la basura")
    item = timers.pending()[0]
    assert (item["label"], item["where"]) == ("saque la basura", "cocina")


def test_everywhere_in_english(house, en):
    skills.quick("Set a timer for 10 minutes everywhere")
    assert timers.pending()[0]["where"] == "all"


def test_if_that_device_isnt_connected_everywhere(house, es):
    kitchen, bedroom = house
    skills.quick("Pon una alarma a las 7")
    hub.remove(bedroom)
    assert alarms.targets(timers.pending()[0]) == [kitchen]


def test_stopped_on_one_it_stops_on_all(monkeypatch):
    from plugins.brain_assistant import Assistant

    class Quiet(Assistant):
        def __init__(self):  # only what stopping uses
            self.ringing, self.sent = None, []
            self.ear = type("Ear", (), {"idle_state": "asleep", "wake": None})()

        def send(self, message):
            self.sent.append(message)

        def _idle_state(self):
            return "asleep"

        def _state(self, state):
            pass

    one, other = Session("a", "x"), Session("b", "y")
    one.brain, other.brain = Quiet(), Quiet()
    hub.add(one)
    hub.add(other)
    item = {"id": 1, "kind": "alarm"}
    one.brain.ringing = other.brain.ringing = item
    one.brain._stop_ringing()
    assert other.brain.ringing is None and {"type": "alarm", "off": True} in other.brain.sent
