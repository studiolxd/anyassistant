"""Streaming over WebSocket (the plugin «stream-api»): a device's microphone and speaker as raw
audio, for the iPhone and iPad app. The page needs WebRTC; an app keeps listening with the
screen off only with its own audio, so it sends it here. To everyone else it is a device like
the page (its id, name and room, its conversation, alarms and «dile a la cocina…»).

    GET /stream?device=<id>   (a WebSocket; pairing as for the page: its cookie)
      → binary: its microphone, 16-bit mono PCM at 48 kHz (any length; 20 ms is usual)
      ← binary: what it says, the same; to play in order
      → / ← text: the page's JSON messages (state, text, timers, alarm, tap, ping/pong…),
        and its own:
        ← {"type": "hello", "eyes": true}: on connecting; whether it may use its camera
        ← {"type": "hush"}: stop playing what is left (it was interrupted)
        → {"type": "log", "text": "…"}: a line for this log (what happens inside the app)
        → {"type": "frame", "jpeg": "<base64>"}: what its camera sees (about once a second
          while awake), for «¿qué ves?»; a full-resolution photo goes to POST /photo (eyes)
        → {"type": "paused", "why": "microphone"|"call"|"interrupted", "app": "Zoom"}: another app
          uses its microphone (a call): nothing is heard until → {"type": "listening"}; the face
          shows ← {"type": "state", "state": "paused", "why": …, "app": …}. If the app can't
          tell (Android silences it: exact zeros arrive), the zeros themselves pause it (Zeros).
"""

import base64
import binascii
import json
import logging
import time
import uuid

import numpy as np
from aiohttp import WSMsgType
from aiohttp import web as http

import echo
import events
import hub
import kernel
import web

log = logging.getLogger("stream")
RATE = 48000
FRESH = 5  # seconds a camera frame is still «now»


class Zeros:
    """Exact digital silence from the device: a microphone always has some noise, but an Android
    app silenced by the system (another app, a call, has the microphone) receives exact zeros.
    feed() says "silenced" after SECONDS of them, "sound" when a real sample arrives again."""

    SECONDS = 2.0

    def __init__(self, seconds: float = SECONDS):
        self.seconds = seconds
        self.zero = 0.0  # seconds of zeros in a row
        self.silenced = False

    def feed(self, pcm: np.ndarray) -> str | None:
        if not len(pcm):
            return None
        if np.any(pcm):
            self.zero = 0.0
            if self.silenced:
                self.silenced = False
                return "sound"
            return None
        self.zero += len(pcm) / RATE
        if not self.silenced and self.zero >= self.seconds:
            self.silenced = True
            return "silenced"
        return None


class Line:
    """Its «connection»: up while the WebSocket is open."""

    def __init__(self):
        self.connectionState = "connected"


class Voice:
    """Its speaker: what it says goes out at once; it is «speaking» until the device has had
    time to play it all."""

    def __init__(self, socket):
        self.socket, self.until = socket, 0.0
        self.trail = echo.Trail()  # the loudness of what went out and when: to know its own echo

    @property
    def speaking(self) -> bool:
        return time.time() < self.until

    @property
    def last_sound(self) -> float:
        return min(time.time(), self.until)

    def play(self, pcm):
        pcm = np.asarray(pcm, np.int16)
        if not len(pcm) or self.socket.closed:
            return
        start = max(time.time(), self.until)
        self.trail.add(pcm, start)
        self.until = start + len(pcm) / RATE
        _soon(self.socket.send_bytes(pcm.tobytes()))

    def stop(self):
        # Always: what the device still has queued may outlast the estimate (its own buffering).
        if not self.socket.closed:
            _soon(self.socket.send_str(json.dumps({"type": "hush"})))
        self.until = 0.0
        self.trail.cut()


def _soon(coroutine):
    import asyncio

    task = asyncio.ensure_future(coroutine)
    task.add_done_callback(lambda t: t.cancelled() or t.exception())  # a closed socket: nothing to do


class Streamer:
    """A device on a WebSocket, as a transport.Session for everyone else."""

    def __init__(self, socket, device: str, agent: str, remote: str = ""):
        self.id = uuid.uuid4().hex[:6]
        self.device, self.agent, self.socket = device, agent, socket
        self.remote = remote  # where it connects from (127.0.0.1: the computer's own app)
        self.pc, self.speaker, self.channel = Line(), Voice(socket), None
        self.frames, self.last_frame = 0, None
        self.picture, self.pictured = None, 0.0  # its camera's last frame (JPEG), and when
        self.zeros = Zeros()  # silenced by the system (Android): exact zeros
        self.brain = web.brain(self.speaker, self.send)

    def hear(self, pcm: np.ndarray):
        """Its microphone; SECONDS of exact zeros pause it (the system gave the microphone to
        another app), the first real sample resumes it."""
        change = self.zeros.feed(pcm)
        ear = getattr(self.brain, "ear", None)
        if change and ear is not None:
            if change == "silenced":
                log.info("[%s] only zeros arrive: its microphone is silenced", self.id)
                ear.pause("microphone", source="zeros")
            else:
                ear.resume("zeros")
        self.brain.hear(pcm)

    def send(self, data: dict):
        if not self.socket.closed:
            _soon(self.socket.send_str(json.dumps(data)))

    def jpeg(self):
        """What its camera sees now (a frame from the last few seconds), or None."""
        return self.picture if time.time() - self.pictured < FRESH else None

    def framed(self, data: dict):
        try:
            self.picture = base64.b64decode(data.get("jpeg") or "", validate=True) or None
        except (binascii.Error, ValueError):
            return
        self.pictured, self.frames = time.time(), self.frames + 1

    def message(self, data: dict):
        token = hub.here.set(self)  # what it starts (a tap, its theme…) is for this device
        try:
            if data.get("type") == "frame":
                self.framed(data)
            elif data.get("type") == "log":  # what happens inside the app, to see it here
                log.info("[%s] app: %s", self.id, str(data.get("text", ""))[:300])
            elif data.get("type") == "ping":
                self.send({"type": "pong", "t": data.get("t")})
            elif hasattr(self.brain, "on_message"):
                self.brain.on_message(data)
        finally:
            hub.here.reset(token)

    async def close(self):
        self.pc.connectionState = "closed"
        hub.remove(self)
        if not self.socket.closed:
            await self.socket.close()


def pcm(raw: bytes) -> np.ndarray:
    """Its microphone: 16-bit samples (an odd byte at the end is dropped)."""
    return np.frombuffer(raw[: len(raw) // 2 * 2], np.int16)


@web.route("GET", "/stream")
async def _stream(request):
    if refusal := web.refused(request):  # pairing, as for the page
        return refusal
    if web.brain is None:
        return http.json_response({"error": "the server isn't running an assistant"}, status=503)
    device = request.query.get("device", "")
    if not device or len(device) > 64 or not device.replace("-", "").replace("_", "").isalnum():
        return http.json_response({"error": "?device=<its id>"}, status=400)
    socket = http.WebSocketResponse(heartbeat=20, max_msg_size=1 << 20)
    await socket.prepare(request)
    streamer = Streamer(socket, device, request.headers.get("User-Agent", ""), request.remote or "")
    for old in hub.add(streamer):  # the same device connecting again: its old connection goes
        await old.close()
    events.emit("connected", streamer)  # its name and room (devices)
    streamer.send({"type": "hello", "eyes": kernel.enabled("eyes")})
    hub.here.set(streamer)  # this task, and what it starts (transcribing, answering…), is for this device
    if hasattr(streamer.brain, "on_connect"):
        streamer.brain.on_connect()
    log.info("[%s] streaming", streamer.id)
    try:
        async for message in socket:
            if message.type == WSMsgType.BINARY:
                streamer.hear(pcm(message.data))
            elif message.type == WSMsgType.TEXT:
                try:
                    streamer.message(json.loads(message.data))
                except ValueError:
                    pass
    finally:
        log.info("[%s] stream ended", streamer.id)
        streamer.pc.connectionState = "closed"
        hub.remove(streamer)
    return socket
