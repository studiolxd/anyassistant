"""The speech recognition model leaves memory when nobody talks (stt.Unloading) and comes back
when a device wakes up or a sentence arrives."""

import logging
import time

import numpy as np
import pytest

import settings
import stt


class Engine(stt.Transcriber):
    """An engine that counts its loads and unloads."""

    name = "fake"

    def __init__(self, can_unload=True):
        super().__init__("es", "fake-model")
        self.loaded, self.loads, self.unloads, self.heard, self.can_unload = True, 0, 0, [], can_unload

    def load(self):
        self.loaded = True
        self.loads += 1

    def unload(self):
        if not self.can_unload:
            return False
        self.loaded = False
        self.unloads += 1
        return True

    def transcribe(self, audio):
        assert self.loaded, "transcribing without the model"
        self.heard.append(len(audio))
        return "hola"


@pytest.fixture
def quiet(monkeypatch):
    """No conversation, the model unloads after UNLOAD_MINUTES."""
    monkeypatch.setattr(settings, "active", {})
    busy = {"now": False}
    engine = Engine()
    wrapped = stt.Unloading(engine, busy=lambda: busy["now"])
    yield engine, wrapped, busy
    wrapped.close()


def test_it_unloads_after_the_minutes_without_use(quiet):
    engine, wrapped, _ = quiet
    assert wrapped.transcribe(np.zeros(8000, dtype=np.float32)) == "hola"
    assert not wrapped.check(now=wrapped.last_used + 4 * 60)
    assert engine.loaded
    assert wrapped.check(now=wrapped.last_used + stt.UNLOAD_MINUTES * 60 + 1)
    assert not engine.loaded and engine.unloads == 1 and not wrapped.loaded
    assert not wrapped.check(now=wrapped.last_used + 10 * 60)  # already gone


def test_not_while_a_conversation_is_going_on(quiet):
    engine, wrapped, busy = quiet
    busy["now"] = True
    assert not wrapped.check(now=wrapped.last_used + 60 * 60)
    assert engine.loaded
    busy["now"] = False
    assert wrapped.check(now=wrapped.last_used + 60 * 60)


def test_zero_means_never(quiet, monkeypatch):
    engine, wrapped, _ = quiet
    monkeypatch.setattr(settings, "active", {"stt_unload_minutes": 0})
    assert not wrapped.check(now=wrapped.last_used + 24 * 60 * 60)
    assert engine.loaded


def test_the_option_sets_the_minutes(quiet, monkeypatch):
    engine, wrapped, _ = quiet
    monkeypatch.setattr(settings, "active", {"stt_unload_minutes": 1})
    assert not wrapped.check(now=wrapped.last_used + 30)
    assert wrapped.check(now=wrapped.last_used + 61)


def test_the_next_sentence_loads_it_again_and_warms_it_up(quiet, caplog):
    engine, wrapped, _ = quiet
    caplog.set_level(logging.INFO, logger="stt")
    wrapped.check(now=wrapped.last_used + (stt.UNLOAD_MINUTES + 1) * 60)
    assert not engine.loaded
    assert wrapped.transcribe(np.ones(16000, dtype=np.float32)) == "hola"
    assert engine.loaded and engine.loads == 1 and wrapped.loaded
    assert engine.heard == [8000, 16000]  # warmed up (half a second of silence), then the sentence
    assert "unloaded" in caplog.text and "loaded again in" in caplog.text


def test_waking_up_starts_loading_before_the_sentence(quiet):
    engine, wrapped, _ = quiet
    wrapped.check(now=wrapped.last_used + (stt.UNLOAD_MINUTES + 1) * 60)
    wrapped.prepare()
    wrapped.prepare()  # twice: one load
    wrapped._preparing.join(5)
    assert engine.loaded and engine.loads == 1
    assert wrapped.transcribe(np.zeros(16000, dtype=np.float32)) == "hola"
    assert engine.loads == 1
    assert not wrapped.check(now=time.time())  # just wanted: it stays


def test_an_engine_that_cannot_unload_stays_and_is_not_asked_again(monkeypatch):
    monkeypatch.setattr(settings, "active", {})
    engine = Engine(can_unload=False)
    wrapped = stt.Unloading(engine, busy=lambda: False)
    try:
        assert not wrapped.check(now=wrapped.last_used + 60 * 60)
        assert engine.loaded and wrapped.loaded
        assert wrapped.minutes() == 0
    finally:
        wrapped.close()


def test_the_ear_prepares_the_model_when_it_wakes_up(monkeypatch):
    import vad
    from plugins.brain_transcriber.ear import Ear

    class Vad:
        def probability(self, window):
            return 0.0

        def reset(self):
            pass

    class Wake:
        phrase, continuous = "Hey, Eva", False

        def reset(self):
            pass

    class Stt:
        prepared = 0

        def prepare(self):
            self.prepared += 1

    monkeypatch.setattr(vad, "create", lambda: Vad())
    engine = Stt()
    ear = Ear(engine, on_state=lambda s: None, on_heard=lambda t, ti: None, wake=Wake())
    assert not ear.awake
    assert ear.wake_up("tap")
    assert ear.awake and engine.prepared == 1


def test_the_assistant_listens_through_an_unloading_engine(monkeypatch):
    """listening() wraps the engine; a conversation anywhere (or a sentence being heard) keeps it."""
    import hub
    from plugins import brain_transcriber

    engine = Engine()
    monkeypatch.setattr(stt, "create", lambda name, language, model=None: engine)
    args = type("Args", (), {"stt": "fake", "stt_model": None, "wake": "none", "record": False,
                             "silence": 0.6, "follow_up": 20})()
    wrapped, wake_factory, _ = brain_transcriber.listening(args)
    try:
        assert isinstance(wrapped, stt.Unloading) and wrapped.engine is engine and wake_factory is None
        assert not brain_transcriber.talking()
        ear = type("Ear", (), {"wake": object(), "awake": True, "speaking": False})()
        session = type("Session", (), {"brain": type("Brain", (), {"ear": ear})()})()
        monkeypatch.setattr(hub, "sessions", {"s1": session})
        assert brain_transcriber.talking()
        ear.awake = False
        assert not brain_transcriber.talking()
        ear.speaking = True
        assert brain_transcriber.talking()
    finally:
        wrapped.close()
