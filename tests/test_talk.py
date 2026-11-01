"""The plugin «talk-api»: one sentence by HTTP (the Apple Watch), the answer as text and voice."""

import asyncio
import base64
import io
import json
import wave

import numpy as np
import pytest

import hub
import kernel
import settings
import web

kernel.load_all()
talk = kernel.load("talk-api")


def a_wav(seconds=1.0, rate=16000) -> bytes:
    out = io.BytesIO()
    with wave.open(out, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(rate)
        w.writeframes((np.sin(np.arange(int(seconds * rate)) / 5) * 8000).astype(np.int16).tobytes())
    return out.getvalue()


class Ear:
    def __init__(self, brain):
        self.brain, self.awake, self.woke, self.slept = brain, False, 0, 0

    def wake_up(self, why):
        if self.awake:
            return False
        self.awake, self.woke = True, self.woke + 1
        self.brain.speaker.play(np.ones(100, np.int16))  # its wake tone
        return True

    def sleep_for(self, reason):
        self.awake, self.slept = False, self.slept + 1

    async def _transcribe(self, audio):
        self.brain.heard_audio = audio
        self.brain.send({"type": "text", "text": "¿qué hora es?"})
        asyncio.ensure_future(self.brain.answer())


class Brain:
    """An assistant that answers after a moment, as the real one does."""

    def __init__(self, speaker, send):
        self.speaker, self.send = speaker, send
        self.ear, self.turn, self.sentences = Ear(self), asyncio.Lock(), asyncio.Queue()
        self.here = None

    async def answer(self):
        async with self.turn:
            self.here = hub.current()
            await asyncio.sleep(0.3)
            self.send({"type": "text", "author": "assistant", "id": 1, "text": "Son las 10.", "partial": False})
            self.speaker.play(np.full(4800, 1000, np.int16))  # 0,1 s at 48 kHz


@pytest.fixture(autouse=True)
def clean(monkeypatch, tmp_path):
    monkeypatch.setattr(kernel.load("devices"), "FILE", tmp_path / "devices.json")  # not your data
    monkeypatch.setattr(hub, "sessions", {})
    monkeypatch.setattr(hub, "active", None)
    monkeypatch.setattr(web, "brain", Brain)
    monkeypatch.setattr(web, "GUARDS", [])
    monkeypatch.setattr(settings, "active", {})
    monkeypatch.setattr(talk, "QUIET", 0.3)
    talk._talkers.clear()


def test_wav_in_any_rate():
    assert len(talk.decode(a_wav(1.0, 44100))) == 16000
    with pytest.raises((ValueError, wave.Error)):
        talk.decode(b"not a wav")


def post(device="watch1", body=None):
    from aiohttp.test_utils import make_mocked_request

    request = make_mocked_request("POST", f"/talk?device={device}", headers={"User-Agent": "AnyAssistant Watch"},
                                  transport=type("T", (), {"get_extra_info": lambda self, k, d=None:
                                                           ("192.168.1.9", 1) if k == "peername" else d})())
    request.read = lambda: asyncio.sleep(0, body if body is not None else a_wav())
    answer = asyncio.run(talk._talk(request))
    return answer.status, json.loads(answer.body)


def test_one_sentence_and_its_answer():
    status, answer = post()
    assert status == 200 and (answer["heard"], answer["answer"]) == ("¿qué hora es?", "Son las 10.")
    with wave.open(io.BytesIO(base64.b64decode(answer["audio"]))) as w:
        assert w.getframerate() == 24000 and w.getnframes() == 2400  # its voice, not its wake tone
    talker = talk._talkers["watch1"]
    assert talker.brain.here is talker  # what it did was for this device
    assert talker.pc.connectionState == "new"  # not «connected» between sentences: no notices to it
    assert hub.sessions[talker.id] is talker and talker.device == "watch1"


def test_the_conversation_goes_on_while_you_keep_talking(monkeypatch):
    post()
    talker = talk._talkers["watch1"]
    post()
    assert (talker.brain.ear.woke, talker.brain.ear.slept) == (1, 0)  # the same conversation
    talker.last -= 60  # a minute later
    post()
    assert (talker.brain.ear.woke, talker.brain.ear.slept) == (2, 1)  # a new one


def test_a_bad_request():
    assert post(device="../x")[0] == 400
    assert post(body=b"nope")[0] == 400


def test_the_watch_is_a_device():
    devices = kernel.load("devices")
    assert devices.kind("AnyAssistant Watch (watchOS 11)") == "Apple Watch"
