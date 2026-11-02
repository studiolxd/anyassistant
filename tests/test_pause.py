"""Paused while another app uses the device's microphone: the ear's state, the devices' messages
(«paused» / «listening»), the zeros an Android app silenced by the system sends, and the option."""

import asyncio
import json
import time

import numpy as np
import pytest
from aiohttp import web as http
from aiohttp.test_utils import TestClient, TestServer

import hub
import kernel
import settings
import vad
import web

kernel.load_all()
from plugins.brain_transcriber import Transcriber, ear as ear_module
from plugins.brain_transcriber.ear import Ear

stream = kernel.load("stream-api")


class FakeVAD:
    def __init__(self):
        self.next = []

    def probability(self, window):
        return self.next.pop(0) if self.next else 0.0

    def reset(self):
        pass


class FakeWake:
    phrase, continuous = "Hey Jarvis", False

    def __init__(self):
        self.heard, self.resets = False, 0

    def listen(self, audio):
        return self.heard

    def reset(self):
        self.resets += 1


@pytest.fixture(autouse=True)
def clean(monkeypatch, tmp_path):
    monkeypatch.setattr(settings, "active", {})
    monkeypatch.setattr(vad, "create", FakeVAD)
    monkeypatch.setattr(hub, "sessions", {})
    monkeypatch.setattr(hub, "active", None)
    monkeypatch.setattr(kernel.load("devices"), "FILE", tmp_path / "devices.json")


def make_ear(wake=None):
    states = []
    ear = Ear(stt=None, on_state=states.append, on_heard=lambda t, g: None, wake=wake)
    return ear, states


def chunk(windows: int = 1, value: int = 1000) -> np.ndarray:
    return np.full(ear_module.WINDOW * 3 * windows, value, np.int16)


# --- The ear ---

def test_paused_it_hears_nothing_and_says_why():
    ear, states = make_ear(FakeWake())
    ear.wake.heard = True  # its name is being said all the time
    ear.pause("microphone", "Zoom")
    assert states == ["paused"] and ear.idle_state == "paused" and ear.pause_reason == ("microphone", "Zoom")
    ear.hear(chunk())
    assert not ear.awake  # not even its name wakes it
    assert not ear.wake_up("tap")  # nor a tap
    ear.resume()
    assert states[-1] == "asleep" and not ear.paused
    ear.hear(chunk())
    assert ear.awake


def test_the_follow_up_clock_does_not_run_while_paused():
    ear, states = make_ear(FakeWake())
    ear.wake_up("tap")
    ear.last_activity = time.time() - 15  # 15 s into a 20 s follow-up
    ear.pause("call")
    ear.paused_at -= 30  # paused for half a minute (a call)
    ear.resume()
    assert ear.awake
    ear.vad.next = [0.0] * 3
    ear.hear(chunk(3))
    assert ear.awake  # still 5 s left: the conversation goes on


def test_several_reasons_each_resumed_on_its_own():
    ear, states = make_ear()
    ear.pause("microphone", source="zeros")
    ear.pause("call", "Phone", source="device")
    assert ear.pause_reason == ("call", "Phone")  # the device's word first
    ear.resume("device")
    assert ear.paused and ear.pause_reason == ("microphone", "")
    ear.resume("zeros")
    assert not ear.paused and states[-1] == "listening"
    ear.resume("zeros")  # again: nothing happens
    assert states.count("listening") == 1


# --- The device's messages, through a brain ---

class Speaker:
    speaking, last_sound = False, 0.0

    def play(self, pcm):
        pass


def brain():
    sent = []
    b = Transcriber(None, FakeWake(), Speaker(), sent.append)
    return b, sent


def test_paused_and_listening_messages():
    b, sent = brain()
    b.on_message({"type": "paused", "why": "microphone", "app": "us.zoom.xos"})
    assert sent[-1] == {"type": "state", "state": "paused", "wake_phrase": "Hey Jarvis", "why": "microphone", "app": "us.zoom.xos"}
    b.on_message({"type": "listening"})
    assert sent[-1] == {"type": "state", "state": "asleep", "wake_phrase": "Hey Jarvis"}


def test_the_option_off_ignores_them():
    settings.active["pause_when_microphone_busy"] = False
    b, sent = brain()
    b.on_message({"type": "paused", "why": "call"})
    assert not b.ear.paused and not sent


def test_the_option_is_sent_to_the_page():
    import options

    assert "pause_when_microphone_busy" in options.SCREEN  # /config «screen»: the apps read it


# --- Zeros: silenced by the system (Android) ---

def test_exact_zeros_pause_and_a_sample_resumes():
    zeros = stream.Zeros(seconds=0.1)
    silence = np.zeros(960, np.int16)  # 20 ms
    assert [zeros.feed(silence) for _ in range(4)] == [None, None, None, None]
    assert zeros.feed(silence) == "silenced"
    assert zeros.feed(silence) is None  # said once
    assert zeros.feed(np.array([0, 0, 1, 0], np.int16)) == "sound"
    assert zeros.feed(silence) is None
    assert zeros.feed(np.zeros(0, np.int16)) is None


def test_zeros_while_it_speaks_dont_count():
    """The iPhone's echo cancellation sends exact zeros while it plays: not another app."""
    zeros = stream.Zeros(seconds=0.1)
    silence = np.zeros(960, np.int16)
    assert [zeros.feed(silence, counting=False) for _ in range(20)] == [None] * 20
    assert [zeros.feed(silence) for _ in range(4)] == [None] * 4  # counted afresh after it
    assert zeros.feed(silence) == "silenced"


def test_quiet_but_real_audio_is_not_silence():
    zeros = stream.Zeros(seconds=0.1)
    for _ in range(20):
        assert zeros.feed(np.array([0, 0, 0, -1, 0, 0], np.int16)) is None


def test_zeros_over_the_stream_pause_the_ear():
    monkeypatch_brain = lambda speaker, send: Transcriber(None, FakeWake(), speaker, send)  # noqa: E731
    web.brain, web.GUARDS = monkeypatch_brain, []

    async def test(client):
        socket = await client.ws_connect("/stream?device=phone1", headers={"User-Agent": "AnyAssistant Android"})
        assert json.loads((await socket.receive()).data)["type"] == "hello"
        assert json.loads((await socket.receive()).data)["state"] == "asleep"
        streamer = next(iter(hub.sessions.values()))
        streamer.zeros.seconds = 0.06
        for _ in range(4):
            await socket.send_bytes(np.zeros(960, np.int16).tobytes())
        paused = json.loads((await socket.receive(timeout=2)).data)
        assert paused == {"type": "state", "state": "paused", "wake_phrase": "Hey Jarvis", "why": "microphone", "app": ""}
        assert streamer.remote and streamer.brain.ear.paused == {"zeros": ("microphone", "")}
        await socket.send_bytes(np.full(960, 5, np.int16).tobytes())
        assert json.loads((await socket.receive(timeout=2)).data)["state"] == "asleep"
        await socket.close()

    async def go():
        app = http.Application()
        app.router.add_get("/stream", stream._stream)
        async with TestClient(TestServer(app)) as client:
            await test(client)
    asyncio.run(go())


def test_status_says_which_device_is_paused():
    b, _ = brain()

    class Session:
        device, agent, remote, frames, pc = "d1", "", "127.0.0.1", 0, None

        def __init__(self):
            self.brain = b

    found = web._device(Session(), True, None)
    assert found["local"] and found["paused"] is None
    b.ear.pause("call", "FaceTime")
    assert web._device(Session(), True, None)["paused"] == {"why": "call", "app": "FaceTime"}


def test_an_iphones_zeros_dont_pause_it():
    """The iPhone's voice processing gives exact zeros whenever nobody speaks: not a silenced
    microphone (it paused at every question); its app says so itself when it loses it."""
    web.brain, web.GUARDS = (lambda speaker, send: Transcriber(None, FakeWake(), speaker, send)), []

    async def test(client):
        socket = await client.ws_connect("/stream?device=iphone1", headers={"User-Agent": "AnyAssistant iPhone"})
        assert json.loads((await socket.receive()).data)["type"] == "hello"
        assert json.loads((await socket.receive()).data)["state"] == "asleep"
        streamer = next(iter(hub.sessions.values()))
        assert streamer.zeros is None
        for _ in range(10):
            await socket.send_bytes(np.zeros(960, np.int16).tobytes())
        await asyncio.sleep(0.2)
        assert not streamer.brain.ear.paused
        await socket.close()

    async def go():
        app = http.Application()
        app.router.add_get("/stream", stream._stream)
        async with TestClient(TestServer(app)) as client:
            await test(client)
    asyncio.run(go())
