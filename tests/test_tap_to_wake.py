"""The plugin «tap-to-wake»: asleep, a tap wakes it up; off, or awake, nothing changes."""

import settings
import kernel

kernel.load_all()  # plugins.* importable
from plugins.brain_transcriber import Transcriber


class Wake:
    phrase = "Hey Jarvis"
    continuous = False

    def reset(self):
        pass


class Speaker:
    speaking = False

    def play(self, pcm):
        pass


def asleep():
    sent = []
    jarvis = Transcriber(stt=None, wake=Wake(), speaker=Speaker(), send=sent.append)
    return jarvis, sent


def test_a_tap_wakes_it_up():
    jarvis, sent = asleep()
    assert not jarvis.ear.awake
    jarvis.on_message({"type": "tap"})
    assert jarvis.ear.awake
    assert {"type": "state", "state": "awake", "wake_phrase": "Hey Jarvis"} in sent


def test_awake_a_tap_changes_nothing():
    jarvis, sent = asleep()
    jarvis.ear.wake_up("test")
    sent.clear()
    jarvis.on_message({"type": "tap"})
    assert jarvis.ear.awake and sent == []


def test_off_a_tap_doesnt_wake_it(monkeypatch):
    monkeypatch.setattr(settings, "active", {"plugins": {"tap-to-wake": False}})
    jarvis, _ = asleep()
    jarvis.on_message({"type": "tap"})
    assert not jarvis.ear.awake
