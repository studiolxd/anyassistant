"""The plugin «stream-api»: the iPhone and iPad app's audio over a WebSocket."""

import asyncio
import base64
import json

import numpy as np
import pytest
from aiohttp import web as http
from aiohttp.test_utils import TestClient, TestServer

import hub
import kernel
import settings
import web

kernel.load_all()
stream = kernel.load("stream-api")


class Brain:
    """Hears the microphone; says something back when it hears enough of it."""

    def __init__(self, speaker, send):
        self.speaker, self.send, self.heard, self.messages, self.here = speaker, send, 0, [], None
        self.connected = False

    def on_connect(self):
        self.connected = True
        self.send({"type": "state", "state": "asleep"})

    def on_message(self, data):
        self.messages.append(data)
        self.here = hub.current()
        if data.get("type") == "tap":
            self.speaker.stop()

    def hear(self, pcm):
        self.heard += len(pcm)
        if self.heard >= 960 * 3:
            self.heard = -10 ** 9  # once
            self.speaker.play(np.full(4800, 1000, np.int16))  # 0,1 s


@pytest.fixture(autouse=True)
def clean(monkeypatch, tmp_path):
    monkeypatch.setattr(kernel.load("devices"), "FILE", tmp_path / "devices.json")  # not your data
    monkeypatch.setattr(hub, "sessions", {})
    monkeypatch.setattr(hub, "active", None)
    monkeypatch.setattr(web, "brain", Brain)
    monkeypatch.setattr(web, "GUARDS", [])
    monkeypatch.setattr(settings, "active", {})


def run(test):
    async def go():
        app = http.Application()
        app.router.add_get("/stream", stream._stream)
        async with TestClient(TestServer(app)) as client:
            await test(client)
    asyncio.run(go())


def test_its_microphone_in_and_its_voice_out():
    async def test(client):
        socket = await client.ws_connect("/stream?device=phone1", headers={"User-Agent": "AnyAssistant iOS"})
        assert json.loads((await socket.receive()).data)["type"] == "hello"
        assert json.loads((await socket.receive()).data) == {"type": "state", "state": "asleep"}
        for _ in range(3):
            await socket.send_bytes(np.zeros(960, np.int16).tobytes())  # 20 ms
        said = await socket.receive(timeout=2)
        assert len(said.data) == 4800 * 2
        streamer = next(iter(hub.sessions.values()))
        assert streamer.device == "phone1" and streamer.pc.connectionState == "connected"
        assert streamer.speaker.speaking  # until the phone has had time to play it
        await socket.send_str(json.dumps({"type": "ping", "t": 5}))
        assert json.loads((await socket.receive()).data) == {"type": "pong", "t": 5}
        await socket.send_str(json.dumps({"type": "tap"}))
        assert json.loads((await socket.receive()).data) == {"type": "hush"}  # stop what is left
        assert streamer.brain.here is streamer  # what the tap started is for this device
        assert kernel.load("devices").load()["phone1"]["name"] == "device"
        await socket.close()
        await asyncio.sleep(0.1)
        assert not hub.sessions and streamer.pc.connectionState == "closed"
    run(test)


def test_connecting_again_replaces_the_old_one():
    async def test(client):
        first = await client.ws_connect("/stream?device=phone1")
        await first.receive()
        await first.receive()
        second = await client.ws_connect("/stream?device=phone1")
        await second.receive()
        await second.receive()
        assert len(hub.sessions) == 1
        assert (await first.receive(timeout=2)).type.name in ("CLOSE", "CLOSED", "CLOSING")
        await second.close()
    run(test)


def test_a_bad_device():
    async def test(client):
        answer = await client.get("/stream?device=../x")
        assert answer.status == 400
    run(test)


def test_what_its_camera_sees():
    async def test(client):
        socket = await client.ws_connect("/stream?device=phone1")
        await socket.receive()
        await socket.receive()
        streamer = next(iter(hub.sessions.values()))
        assert streamer.jpeg() is None  # nothing yet
        await socket.send_str(json.dumps({"type": "frame", "jpeg": base64.b64encode(b"\xff\xd8jpeg").decode()}))
        await asyncio.sleep(0.05)
        assert streamer.jpeg() == b"\xff\xd8jpeg" and streamer.frames == 1
        streamer.pictured -= 60  # a minute ago: not «now» any more
        assert streamer.jpeg() is None
        await socket.send_str(json.dumps({"type": "frame", "jpeg": "not base64!"}))
        await asyncio.sleep(0.05)
        assert streamer.frames == 1
        await socket.close()
    run(test)
