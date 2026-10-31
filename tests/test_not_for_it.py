"""Not every sentence is for it: a short follow-up window, and the LLM may stay quiet."""

import asyncio
import time

import pytest

import llm
import settings
import kernel

kernel.load_all()  # plugins.* importable
from plugins.brain_assistant import Assistant
from plugins.brain_transcriber.ear import Ear


class FakeLLM:
    def __init__(self, *pieces):
        self.pieces, self.heard = pieces, []

    async def answer(self, text, image=None):
        self.heard.append(text)
        for piece in self.pieces:
            yield piece


def assistant(model, monkeypatch, tmp_path):
    monkeypatch.setattr(settings, "PATH", tmp_path / "settings.json")
    a = object.__new__(Assistant)
    a.llm, a.tts, a.turn, a.number, a.cut = model, None, asyncio.Lock(), 1, 0
    a.sent, a.transcript, a.saying, a.said, a.ringing, a.doubt = [], [("user", "x")], [], [], None, False
    a.detail = llm.detail()
    a.send = a.sent.append
    a.ear = type("Ear", (), {"idle_state": "awake"})()
    a.wake = None
    return a


def texts(a):
    return [m["text"] for m in a.sent if m.get("type") == "text"]


def test_silence_says_and_shows_nothing(monkeypatch, tmp_path, en):
    a = assistant(FakeLLM("<sil", "ence>"), monkeypatch, tmp_path)
    asyncio.run(a._answer("Thanks, Gabriela. Bye!"))
    assert texts(a) == [] and a.transcript == []  # not for its memory either


def test_a_normal_answer_goes_through(monkeypatch, tmp_path, en):
    a = assistant(FakeLLM("It's ", "sunny."), monkeypatch, tmp_path)
    asyncio.run(a._answer("How's the weather?"))
    assert texts(a)[-1] == "It's sunny."


def test_an_answer_that_only_starts_like_it(monkeypatch, tmp_path, en):
    a = assistant(FakeLLM("<"), monkeypatch, tmp_path)
    asyncio.run(a._answer("Write a less-than sign"))
    assert texts(a)[-1] == "<"


def test_it_can_be_turned_off(monkeypatch, tmp_path, en):
    monkeypatch.setattr(settings, "active", {"ignore_others": False})
    assert llm.SILENCE not in llm.instructions()
    a = assistant(FakeLLM("<silence>"), monkeypatch, tmp_path)
    asyncio.run(a._answer("Hi"))
    assert texts(a)[-1] == "<silence>"


def test_on_by_default(monkeypatch, en):
    monkeypatch.setattr(settings, "active", {})
    assert llm.SILENCE in llm.instructions()


def test_after_a_dubious_wake_up_the_first_sentence_carries_the_doubt(monkeypatch, tmp_path, en):
    model = FakeLLM("Sure.")
    a = assistant(model, monkeypatch, tmp_path)
    a.doubt = True
    asyncio.run(a._answer("So yes, a time of change."))
    asyncio.run(a._answer("And tomorrow?"))
    assert "isn't clear this was said to you" in model.heard[0]
    assert "isn't clear" not in model.heard[1]


def test_dubious_wake_ups(monkeypatch):
    from plugins.wake_whisper import WhisperWakeWord

    word = object.__new__(WhisperWakeWord)
    word.keys, word.threshold, word.prompt = ["jarvis"], 0.85, "The assistant's name is Jarvis."
    word.model, word.dubious = "x", False
    for text, dubious in (("Hey Jarvis.", False), ("Oye Jarvis, ¿qué hora es?", False),
                          ("Bueno, vale, Jarvis, ya", True),
                          ("Jarvis y luego te lo dejo explicado pues mira porque es largo y tiene muchas cosas", True)):
        word._transcribe = lambda *args, t=text: t
        assert word._search(None) is True
        assert word.dubious is dubious, text


class Clock:
    def __init__(self):
        self.now = 1000.0

    def __call__(self):
        return self.now


def test_follow_up_window(monkeypatch):
    """It goes back to sleep after follow_up seconds without speech, but not while busy."""
    clock = Clock()
    monkeypatch.setattr("plugins.brain_transcriber.ear.time.time", clock)
    monkeypatch.setattr(settings, "active", {"follow_up": 20})
    slept = []
    ear = object.__new__(Ear)
    ear.wake, ear.awake, ear.speaking, ear.last_activity, ear.follow_up = object(), True, False, clock.now, 20
    ear.deaf, ear.pre_roll = (lambda: False), []
    busy = [False]
    ear.busy = lambda: busy[0]
    ear.vad = type("Silence", (), {"probability": lambda self, window: 0.0, "reset": lambda self: None})()
    ear._sleep = lambda reason: slept.append(reason)
    clock.now += 15
    ear._window(None)
    assert not slept
    busy[0] = True  # thinking: the clock doesn't run
    clock.now += 30
    ear._window(None)
    assert not slept
    busy[0] = False
    clock.now += 21
    ear._window(None)
    assert slept == ["20 s without speech"]
