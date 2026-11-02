"""The screen follows the voice: «speaking» says which part of the answer starts playing, when it does."""

import asyncio
import time

import numpy as np

import llm
import settings
import kernel
from audio import Speaker

kernel.load_all()  # plugins.* importable
from plugins.brain_assistant import Assistant

stream = kernel.load("stream-api")


class FakeLLM:
    def __init__(self, *pieces):
        self.pieces = pieces

    async def answer(self, text, image=None):
        for piece in self.pieces:
            yield piece


class Voice:
    """A speaker that plays each sentence for `seconds` after what is queued (as the real ones)."""

    def __init__(self, seconds=0.0):
        self.seconds, self.until, self.played = seconds, 0.0, []

    @property
    def speaking(self):
        return time.time() < self.until

    def play(self, pcm):
        starts = max(time.time(), self.until)
        self.until = starts + self.seconds
        self.played.append(starts)
        return starts

    def stop(self):
        self.until = 0.0


class TTS:
    def synthesize(self, sentence):
        return np.ones(480, np.int16)


def assistant(monkeypatch, tmp_path, model=None, speaker=None):
    monkeypatch.setattr(settings, "PATH", tmp_path / "settings.json")
    a = object.__new__(Assistant)
    a.llm, a.tts, a.turn, a.number, a.cut = model, TTS(), asyncio.Lock(), 1, 0
    a.sent, a.transcript, a.saying, a.said, a.ringing, a.doubt = [], [], [], [], None, False
    a.detail = llm.detail()
    a.send = a.sent.append
    a.speaker = speaker or Voice()
    a.sentences = asyncio.Queue()
    a.ear = type("Ear", (), {"idle_state": "awake"})()
    a.wake = None
    a._state = lambda state: None
    return a


def speaking(a):
    return [m for m in a.sent if m.get("type") == "speaking"]


def test_each_sentence_with_its_place_in_the_answer(monkeypatch, tmp_path, en):
    a = assistant(monkeypatch, tmp_path, FakeLLM("Rice with ", "eggs. Fry the rice first!  Then", " the eggs: ",
                                                 "two.\nServe it hot"))
    asyncio.run(a._answer("What can I cook?"))
    answer = [m for m in a.sent if m.get("type") == "text"][-1]["text"]
    queued = []
    while not a.sentences.empty():
        queued.append(a.sentences.get_nowait())
    said = [(sentence, where[0]) for _, sentence, *where in queued if sentence]
    assert [s for s, _ in said] == ["Rice with eggs.", "Fry the rice first!", "Then the eggs:", "two.", "Serve it hot"]
    for sentence, at in said:
        assert answer[at:at + len(sentence)] == sentence


def test_counted_as_the_screens_count_an_emoji_is_two(monkeypatch, tmp_path, en):
    a = assistant(monkeypatch, tmp_path, FakeLLM("Sunny 🌞 today. And warm."))
    asyncio.run(a._answer("Weather?"))
    answer = [m for m in a.sent if m.get("type") == "text"][-1]["text"]
    a.sentences.get_nowait()
    _, sentence, at = a.sentences.get_nowait()
    assert sentence == "And warm." and at == len(answer.encode("utf-16-le")) // 2 - len("And warm.")


def test_a_fixed_sentence_is_the_whole_text(monkeypatch, tmp_path, en):
    a = assistant(monkeypatch, tmp_path)
    a._say("Restarting.")
    assert a.sentences.get_nowait()[1:] == ("Restarting.", 0)


def test_told_when_each_sentence_starts_playing_not_when_it_is_queued(monkeypatch, tmp_path, en):
    a = assistant(monkeypatch, tmp_path, FakeLLM("One. Two. Three."), Voice(seconds=0.15))

    async def go():
        mouth = asyncio.ensure_future(a._mouth())
        await a._answer("Count")
        await asyncio.sleep(0.05)
        early = [m["start"] for m in speaking(a)]
        await asyncio.sleep(0.45)
        mouth.cancel()
        return early

    early = asyncio.run(go())
    assert early == [0]  # «Two» and «Three» are queued behind it, not playing yet
    assert [(m["start"], m["end"]) for m in speaking(a)] == [(0, 4), (5, 9), (10, 16)]
    assert {m["id"] for m in speaking(a)} == {a.number}


def test_nothing_once_it_is_stopped(monkeypatch, tmp_path, en):
    a = assistant(monkeypatch, tmp_path, FakeLLM("One. Two. Three."), Voice(seconds=0.2))

    async def go():
        mouth = asyncio.ensure_future(a._mouth())
        await a._answer("Count")
        await asyncio.sleep(0.05)
        a.cut = a.number  # a tap
        await asyncio.sleep(0.5)
        mouth.cancel()

    asyncio.run(go())
    assert [m["start"] for m in speaking(a)] == [0]


def test_the_speakers_say_when_it_starts():
    speaker = Speaker()
    now = time.time()
    assert abs(speaker.play(np.ones(48000, np.int16)) - now) < 0.05
    assert abs(speaker.play(np.ones(4800, np.int16)) - (now + 1)) < 0.05  # after the second queued

    class Socket:
        closed = False

        async def send_bytes(self, data):
            pass

    async def go():
        voice = stream.Voice(Socket())
        first = voice.play(np.ones(24000, np.int16))
        return first, voice.play(np.ones(4800, np.int16))

    first, second = asyncio.run(go())
    assert abs(second - first - 0.5) < 0.01
