"""Transport: one WebRTC session with the phone.

Receives microphone and camera, sends the Speaker track back and keeps a
"control" DataChannel for JSON messages. It knows nothing about the brain: it is
given a factory brain(speaker, send) that returns something with hear(pcm).
"""

import asyncio
import io
import json
import logging

from aiortc import RTCConfiguration, RTCPeerConnection, RTCSessionDescription

import hub
from audio import Speaker, to_mono

log = logging.getLogger("transport")


class Session:
    def __init__(self, session_id: str, brain, device: str | None = None):
        self.id = session_id
        self.device = device  # the page's own id: the same device connecting again
        self.agent = ""  # its browser's User-Agent
        # No STUN: on the local network it is useless, and aiortc's default (a
        # Google server) made every connection take ~5 s to answer.
        self.pc = RTCPeerConnection(RTCConfiguration(iceServers=[]))
        self.channel = None
        self.speaker = Speaker()
        self.brain = brain(self.speaker, self.send)
        self.last_frame = None
        self.frames = 0
        self._tasks = []

        @self.pc.on("datachannel")
        def on_datachannel(channel):
            self.channel = channel
            if hasattr(self.brain, "on_connect"):
                self.brain.on_connect()

            @channel.on("message")
            def on_message(message):
                self._message(json.loads(message))

        @self.pc.on("track")
        def on_track(track):
            log.info("[%s] track received: %s", self.id, track.kind)
            if track.kind == "audio":
                self.pc.addTrack(self.speaker)
                self._tasks.append(asyncio.ensure_future(self._read_audio(track)))
            elif track.kind == "video":
                self._tasks.append(asyncio.ensure_future(self._read_video(track)))

        @self.pc.on("connectionstatechange")
        async def on_state():
            log.info("[%s] connection: %s", self.id, self.pc.connectionState)
            if self.pc.connectionState in ("failed", "closed"):
                await self.close()

    async def answer(self, sdp: str, kind: str) -> RTCSessionDescription:
        await self.pc.setRemoteDescription(RTCSessionDescription(sdp=sdp, type=kind))
        await self.pc.setLocalDescription(await self.pc.createAnswer())
        return self.pc.localDescription

    def send(self, data: dict):
        if self.channel and self.channel.readyState == "open":
            self.channel.send(json.dumps(data))

    def _message(self, data: dict):
        if data.get("type") == "ping":
            self.send({"type": "pong", "t": data["t"]})
        elif hasattr(self.brain, "on_message"):
            self.brain.on_message(data)

    async def _read_audio(self, track):
        try:
            while True:
                self.brain.hear(to_mono(await track.recv()))
        except Exception:
            log.info("[%s] audio ended", self.id)

    async def _read_video(self, track):
        try:
            while True:
                self.last_frame = await track.recv()
                self.frames += 1
        except Exception:
            pass

    def jpeg(self) -> bytes | None:
        if self.last_frame is None:
            return None
        buffer = io.BytesIO()
        self.last_frame.to_image().save(buffer, format="JPEG", quality=75)
        return buffer.getvalue()

    async def close(self):
        hub.remove(self)
        for task in self._tasks:
            task.cancel()
        await self.pc.close()
