"""Talking over HTTP (the plugin «talk-api»): one spoken sentence in, the answer out, as text and
voice. For devices that can't keep a WebRTC call open: the Apple Watch (press to talk), later a
Siri shortcut. Each is a device like the others (its id, its name and room in «devices», its
own conversation, its voice checked by «voices», «dile a la cocina…»), only it hears one
sentence at a time, when you press.

    POST /talk?device=<id>   a WAV (16-bit mono, any rate)
      → {"heard": "¿qué hora es?", "answer": "Son las 10 y 20.", "audio": "<a WAV, 24 kHz, base64>"}

Pairing (the plugin «pairing») as for the page: POST /pair {"code"} once, then its cookie.
A conversation lasts while you keep talking (follow_up seconds between sentences); after
that, the next press starts a new one.
"""

import asyncio
import base64
import io
import logging
import re
import time
import uuid
import wave

import numpy as np
from aiohttp import web as http
from scipy.signal import resample_poly

import events
import hub
import settings
import web

log = logging.getLogger("talk")
QUIET = 1.2  # seconds with nothing new: the answer is over
WAIT = 90  # seconds an answer may take at most
LATE = 15  # seconds a skill may take to answer in the background (the weather…)
OUT = 24000  # the answer's audio rate


class Capture:
    """The speaker of a device that isn't on a call: it keeps what would be said."""
    speaking = False
    last_sound = 0.0

    def __init__(self):
        self.pcm, self.at = [], 0.0

    def play(self, pcm):
        self.pcm.append(np.asarray(pcm, np.int16))
        self.at = time.time()

    def stop(self):
        self.pcm = []


class Line:
    """Its «connection»: up only while a sentence is being answered (so notices and alarms,
    which it couldn't play, don't count on it)."""

    def __init__(self):
        self.talking = False

    @property
    def connectionState(self) -> str:
        return "connected" if self.talking else "new"


class Talker:
    """A device that talks by HTTP, as a transport.Session for everyone else."""
    press_to_talk = True  # never «connected» between sentences: the devices say so

    def __init__(self, device: str, agent: str):
        self.id = uuid.uuid4().hex[:6]
        self.device, self.agent = device, agent
        self.pc, self.speaker, self.channel = Line(), Capture(), None
        self.sent, self.frames, self.last = [], 0, 0.0
        self.turn = asyncio.Lock()  # one sentence at a time
        self.brain = web.brain(self.speaker, self.send)

    def send(self, data: dict):
        self.sent.append(data)
        self.speaker.at = time.time()  # something happened

    def jpeg(self):
        return None

    async def close(self):
        hub.remove(self)


_talkers: dict[str, Talker] = {}


def decode(raw: bytes) -> np.ndarray:
    """A 16-bit WAV → 16 kHz mono float audio, as the ear wants it."""
    with wave.open(io.BytesIO(raw)) as w:
        if w.getsampwidth() != 2:
            raise ValueError("a 16-bit WAV")
        pcm = np.frombuffer(w.readframes(w.getnframes()), np.int16).astype(np.float32) / 32768
        if w.getnchannels() > 1:
            pcm = pcm.reshape(-1, w.getnchannels()).mean(axis=1)
        rate = w.getframerate()
    if rate != 16000:
        from math import gcd

        g = gcd(16000, rate)
        pcm = resample_poly(pcm, 16000 // g, rate // g)
    return louder(pcm.astype(np.float32))


LOUD = 0.5  # the peak a quiet sentence is raised to
MOST = 30.0  # at most this much louder (beyond, it is only noise)


def louder(pcm: np.ndarray) -> np.ndarray:
    """A watch's microphone records low: a quiet sentence is raised so the transcriber hears it."""
    peak = float(np.abs(pcm).max()) if len(pcm) else 0.0
    if 0 < peak < LOUD:
        pcm = pcm * min(LOUD / peak, MOST)
    return pcm


def encode(chunks: list) -> bytes:
    """What it said (48 kHz) → a 24 kHz WAV."""
    pcm = np.concatenate(chunks) if chunks else np.zeros(0, np.int16)
    pcm = resample_poly(pcm.astype(np.float32), 1, 2).astype(np.int16) if len(pcm) else pcm
    out = io.BytesIO()
    with wave.open(out, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(OUT)
        w.writeframes(pcm.tobytes())
    return out.getvalue()


def _answered(talker) -> bool:
    return any(m.get("type") == "text" and m.get("author") == "assistant" and not m.get("partial") for m in talker.sent)


def _heard(talker) -> bool:
    return any(m.get("type") == "text" and "author" not in m for m in talker.sent)


async def _until_quiet(talker, since: float):
    """Until the answer is over: said in full and nothing new for QUIET seconds; or nothing heard
    (dropped: not for it, an unknown voice…); or heard but no answer for LATE seconds."""
    brain = talker.brain
    while time.time() - since < WAIT:
        await asyncio.sleep(0.2)
        if brain.turn.locked() or not brain.sentences.empty():
            continue
        idle = time.time() - max(talker.speaker.at, since)
        if _answered(talker):
            if idle > QUIET:
                return
        elif idle > (LATE if _heard(talker) else 3 * QUIET):
            return


async def talk(talker: Talker, audio: np.ndarray) -> dict:
    """One sentence: wakes its brain (a new conversation if the last sentence was long ago),
    hears it, waits for the whole answer, and returns it."""
    brain = talker.brain
    follow_up = settings.get("follow_up") or 20
    async with talker.turn:
        talker.pc.talking = True
        token = hub.here.set(talker)  # what it does is for this device
        try:
            if brain.ear.awake and time.time() - talker.last > follow_up:
                brain.ear.sleep_for(f"{follow_up:g} s since the last sentence")  # that conversation is over
            brain.ear.wake_up("press to talk")
            talker.sent.clear()
            talker.speaker.stop()  # not its wake and sleep tones
            since = time.time()
            await brain.ear._transcribe(audio)
            await _until_quiet(talker, since)
            talker.last = time.time()
        finally:
            hub.here.reset(token)
            talker.pc.talking = False
    heard = next((m["text"] for m in talker.sent if m.get("type") == "text" and "author" not in m), "")
    answer = " ".join(m["text"] for m in talker.sent
                      if m.get("type") == "text" and m.get("author") == "assistant" and not m.get("partial"))
    return {"heard": heard, "answer": answer, "audio": base64.b64encode(encode(talker.speaker.pcm)).decode()}


@web.route("POST", "/talk")
async def _talk(request):
    if refusal := web.refused(request):  # pairing, as for the page
        return refusal
    if web.brain is None:
        return http.json_response({"error": "the server isn't running an assistant"}, status=503)
    device = request.query.get("device", "")
    if not re.fullmatch(r"[A-Za-z0-9_-]{1,64}", device):
        return http.json_response({"error": "?device=<its id>"}, status=400)
    try:
        audio = decode(await request.read())
    except (ValueError, EOFError, wave.Error) as e:
        return http.json_response({"error": f"a WAV, please ({e})"}, status=400)
    talker = _talkers.get(device)
    if talker is None or hub.sessions.get(talker.id) is not talker:
        talker = _talkers[device] = Talker(device, request.headers.get("User-Agent", ""))
        hub.add(talker)
    events.emit("connected", talker)  # its name and room, when it was last seen (devices)
    log.info("[%s] a sentence (%.1f s, peak %.2f)", talker.id, len(audio) / 16000,
             float(np.abs(audio).max()) if len(audio) else 0.0)
    return http.json_response(await talk(talker, audio))
