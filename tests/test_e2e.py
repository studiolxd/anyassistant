"""End to end: the real server, spoken to over WebRTC like the phone does.

Slow (it loads the models) and only on a Mac: run with `uv run pytest -m e2e`.
The voices are made with `say`, so no recordings live in the repository.
"""

import asyncio
import fractions
import json
import os
import shutil
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.request
import wave

import numpy as np
import pytest

from conftest import ROOT

pytestmark = pytest.mark.e2e
RATE = 48000


def speech(tmp_path, text, voice) -> np.ndarray:
    """`say` → 48 kHz mono PCM, followed by silence so the sentence ends."""
    aiff, wav = tmp_path / "voice.aiff", tmp_path / "voice.wav"
    subprocess.run(["say", "-v", voice, "-o", aiff, text], check=True)
    subprocess.run(["afconvert", "-f", "WAVE", "-d", "LEI16@48000", "-c", "1", aiff, wav], check=True)
    with wave.open(str(wav)) as w:
        pcm = np.frombuffer(w.readframes(w.getnframes()), np.int16)
    silence = np.zeros(RATE, np.int16)
    return np.concatenate([silence, pcm, silence * 2])


@pytest.fixture
def server(tmp_path):
    """Starts server/main.py with the given options; returns its URL."""
    processes = []

    def start(*options):
        with socket.socket() as s:
            s.bind(("127.0.0.1", 0))
            port = s.getsockname()[1]
        log = open(tmp_path / "server.log", "w")
        process = subprocess.Popen(
            [sys.executable, ROOT / "server" / "main.py", "--host", "127.0.0.1", "--port", str(port), *options],
            cwd=ROOT, stdout=log, stderr=subprocess.STDOUT, env={**os.environ, "PYTHONUNBUFFERED": "1", "JARVIS_SETTINGS": str(tmp_path / "settings.json"),
                 "JARVIS_PAIRED": str(tmp_path / "paired.json"), "JARVIS_MEMORY": str(tmp_path / "memory.json")},
        )
        processes.append(process)
        url = f"http://127.0.0.1:{port}"
        for _ in range(180):
            if process.poll() is not None:
                pytest.fail("the server stopped:\n" + (tmp_path / "server.log").read_text()[-3000:])
            try:
                urllib.request.urlopen(url + "/status", timeout=1)
                return url
            except OSError:
                time.sleep(1)
        pytest.fail("the server didn't start in 3 minutes")

    yield start
    for process in processes:
        process.terminate()
        try:
            process.wait(15)
        except subprocess.TimeoutExpired:
            process.kill()


async def talk(url, pcm, until, timeout=60, image=None, photo=None):
    """Plays `pcm` as the phone's microphone; returns (messages, sound that came back).

    With `image` (a PIL image), the phone's camera shows it; with `photo` (JPEG bytes),
    that is the full-resolution photo it takes when asked to.

    Waits until until(messages) is true (or the timeout) after the audio ends.
    """
    import aiohttp
    from aiortc import MediaStreamTrack, RTCPeerConnection, RTCSessionDescription
    from av import AudioFrame

    class Microphone(MediaStreamTrack):
        kind = "audio"

        def __init__(self):
            super().__init__()
            self.pts = 0

        async def recv(self):
            await asyncio.sleep(0.02)
            chunk = pcm[self.pts:self.pts + 960]
            chunk = np.pad(chunk, (0, 960 - len(chunk)))
            frame = AudioFrame.from_ndarray(chunk.reshape(1, -1), format="s16", layout="mono")
            frame.sample_rate, frame.pts = RATE, self.pts
            frame.time_base = fractions.Fraction(1, RATE)
            self.pts += 960
            return frame

    class Camera(MediaStreamTrack):
        kind = "video"

        def __init__(self):
            super().__init__()
            self.pts = 0

        async def recv(self):
            from av import VideoFrame

            await asyncio.sleep(0.1)
            frame = VideoFrame.from_image(image)
            frame.pts, frame.time_base = self.pts, fractions.Fraction(1, 90000)
            self.pts += 9000
            return frame

    pc = RTCPeerConnection()
    pc.addTrack(Microphone())
    if image is not None:
        pc.addTrack(Camera())
    channel = pc.createDataChannel("control")
    messages, loudest = [], []
    def on_message(m):
        messages.append(json.loads(m))
        if messages[-1].get("type") == "photo" and photo:
            asyncio.ensure_future(send_photo(messages[-1]["id"]))

    async def send_photo(number):
        async with aiohttp.ClientSession() as http:
            await http.post(f"{url}/photo?id={number}", data=photo)

    channel.on("message", on_message)

    @pc.on("track")
    def on_track(track):
        async def read():
            while True:
                loudest.append(int(np.abs((await track.recv()).to_ndarray()).max()))

        asyncio.ensure_future(read())

    await pc.setLocalDescription(await pc.createOffer())
    async with aiohttp.ClientSession() as http:
        response = await http.post(url + "/offer", json={"sdp": pc.localDescription.sdp,
                                                          "type": pc.localDescription.type})
        await pc.setRemoteDescription(RTCSessionDescription(**await response.json()))
    await asyncio.sleep(len(pcm) / RATE)
    deadline = time.time() + timeout
    while not until(messages) and time.time() < deadline:
        await asyncio.sleep(0.5)
    await asyncio.sleep(1)  # the rest of the sound
    await pc.close()
    return messages, loudest


def states(messages):
    return [m["state"] for m in messages if m.get("type") == "state"]


def final_texts(messages, author=None):
    return [m["text"] for m in messages
            if m.get("type") == "text" and not m.get("partial") and m.get("author") == author]


def test_page_and_settings(server, tmp_path):
    (tmp_path / "settings.json").write_text(json.dumps({"name": "Viernes", "face": "orb", "video": "low",
                                                        "show_time": False, "history": 0}))
    url = server("--mode", "parrot", "--lang", "es")
    html = urllib.request.urlopen(url + "/").read().decode()
    assert 'id="face"' in html and '<html lang="es"' in html and "<title>Viernes</title>" in html
    assert '<html lang="es"' in urllib.request.urlopen(url + "/monitor").read().decode()
    config = json.load(urllib.request.urlopen(url + "/config"))
    assert config["lang"] == "es" and config["ui"]["start"]
    assert (config["name"], config["face"], config["video"]) == ("Viernes", "orb", "low")
    assert config["screen"]["show_time"] is False and config["screen"]["history"] == 0
    assert config["screen"]["show_date"] is True  # the default


def test_bad_settings_stop_it(tmp_path):
    (tmp_path / "settings.json").write_text(json.dumps({"face": "smiley"}))
    result = subprocess.run([sys.executable, ROOT / "server" / "main.py", "--mode", "parrot"], cwd=ROOT,
                            capture_output=True, text=True, timeout=60,
                            env={**os.environ, "JARVIS_SETTINGS": str(tmp_path / "settings.json")})
    assert result.returncode != 0 and "smiley" in result.stderr


def test_parrot_repeats(server, tmp_path):
    url = server("--mode", "parrot")
    messages, loudest = asyncio.run(talk(url, speech(tmp_path, "Testing, one, two, three", "Samantha"),
                                         until=lambda m: "repeating" in states(m)))
    assert "recording" in states(messages) and "repeating" in states(messages)
    assert max(loudest, default=0) > 1500  # its voice came back


def test_transcribes_spanish(server, tmp_path):
    url = server("--mode", "transcribe", "--lang", "es", "--wake", "none")
    messages, _ = asyncio.run(talk(url, speech(tmp_path, "¿Qué hora es?", "Mónica"),
                                   until=lambda m: final_texts(m)))
    assert "hora" in " ".join(final_texts(messages)).lower()


def test_wake_word_then_sleep(server, tmp_path):
    url = server("--mode", "transcribe", "--lang", "en")
    pcm = np.concatenate([speech(tmp_path, "Hey Jarvis", "Samantha"),
                          speech(tmp_path, "What time is it?", "Samantha"),
                          speech(tmp_path, "Go to sleep", "Samantha")])
    messages, _ = asyncio.run(talk(url, pcm, until=lambda m: states(m)[-1:] == ["asleep"] and final_texts(m)))
    seen = states(messages)
    assert seen[0] == "asleep" and "awake" in seen and seen[-1] == "asleep"
    assert "time" in " ".join(final_texts(messages)).lower()


def test_assistant_answers_out_loud(server, tmp_path):
    """With Apple's local model: no account or network needed."""
    url = server("--mode", "assistant", "--lang", "en", "--wake", "none", "--llm", "apple")
    messages, loudest = asyncio.run(talk(url, speech(tmp_path, "What day of the week is today?", "Samantha"),
                                         until=lambda m: final_texts(m, "assistant") and states(m)[-1:] == ["listening"],
                                         timeout=90))
    answer = " ".join(final_texts(messages, "assistant"))
    assert answer
    assert "thinking" in states(messages) and "speaking" in states(messages)
    assert max(loudest, default=0) > 1500


def test_switch_language_by_voice(server, tmp_path):
    url = server("--mode", "assistant", "--lang", "en", "--wake", "none", "--llm", "apple")
    messages, _ = asyncio.run(talk(url, speech(tmp_path, "Switch to Spanish", "Samantha"),
                                   until=lambda m: final_texts(m, "assistant"), timeout=30))
    assert "Spanish" in " ".join(final_texts(messages, "assistant"))
    assert json.loads((tmp_path / "settings.json").read_text())["language"] == "es"
    # It restarts by itself, in Spanish despite --lang en.
    for _ in range(120):
        try:
            if json.load(urllib.request.urlopen(url + "/config", timeout=1))["lang"] == "es":
                return
        except OSError:
            pass
        time.sleep(1)
    pytest.fail("it didn't come back in Spanish")


def test_interrupt_by_voice(server, tmp_path):
    """«Jarvis, stop» in the middle of a long answer: it stops talking."""
    url = server("--mode", "assistant", "--lang", "en", "--llm", "apple")
    pcm = np.concatenate([speech(tmp_path, "Hey Jarvis", "Samantha"),
                          speech(tmp_path, "Tell me a story about a dragon.", "Samantha"),
                          speech(tmp_path, "Jarvis, stop.", "Samantha")])  # right as it starts answering
    log = tmp_path / "server.log"
    messages, _ = asyncio.run(talk(url, pcm, until=lambda m: "interrupted by voice" in log.read_text(), timeout=20))
    assert "interrupted by voice" in log.read_text()
    seen = states(messages)
    assert "speaking" in seen and seen[-1] == "awake"


def lan_address():
    """The Mac's address on the network: requests from it don't count as the Mac itself."""
    for interface in ("en0", "en1"):
        address = subprocess.run(["ipconfig", "getifaddr", interface], capture_output=True, text=True).stdout.strip()
        if address:
            return address
    pytest.skip("no network address")


def test_pairing(server, tmp_path):
    (tmp_path / "settings.json").write_text(json.dumps({"pairing": True}))
    local = server("--mode", "parrot", "--host", "0.0.0.0")
    remote = local.replace("127.0.0.1", lan_address())

    def request(url, body=None, cookie=None):
        req = urllib.request.Request(url, data=json.dumps(body).encode() if body is not None else None,
                                     headers={"Content-Type": "application/json", **({"Cookie": cookie} if cookie else {})})
        try:
            response = urllib.request.urlopen(req, timeout=5)
            return response.status, response
        except urllib.error.HTTPError as e:
            return e.code, e

    assert json.load(urllib.request.urlopen(remote + "/config"))["paired"] is False
    assert request(remote + "/status")[0] == 403
    assert request(remote + "/video.mjpg")[0] == 403
    assert request(remote + "/offer", {"sdp": "", "type": "offer"})[0] == 403
    assert request(remote + "/pairing", {})[0] == 403  # codes only from the Mac
    assert request(local + "/status")[0] == 200  # the Mac itself, always

    code = json.load(request(local + "/pairing", {})[1])["code"]
    assert request(remote + "/pair", {"code": "000000" if code != "000000" else "111111"})[0] == 403
    status, response = request(remote + "/pair", {"code": code})
    assert status == 200
    cookie = response.headers["Set-Cookie"].split(";")[0]
    assert request(remote + "/status", cookie=cookie)[0] == 200
    assert request(remote + "/pair", {"code": code})[0] == 403  # one device per code

    request(local + "/pairing?forget=1", {})
    assert request(remote + "/status", cookie=cookie)[0] == 403


@pytest.mark.skipif(not shutil.which("claude"), reason="needs Claude Code signed in")
def test_eyes_with_claude(server, tmp_path):
    """It reads what the camera shows: asked to («read this») and on its own (no such word)."""
    from PIL import Image, ImageDraw, ImageFont

    image = Image.new("RGB", (640, 480), "white")
    ImageDraw.Draw(image).text((150, 200), "MILK  BREAD  42", fill="black", font=ImageFont.load_default(size=44))
    (tmp_path / "settings.json").write_text(json.dumps({"eyes": True}))
    url = server("--mode", "assistant", "--lang", "en", "--wake", "none", "--llm", "claude", "--tts", "none")
    done = lambda m: len(final_texts(m, "assistant")) >= 2  # noqa: E731
    pcm = np.concatenate([speech(tmp_path, "Read what I'm holding.", "Samantha"), np.zeros(RATE * 12, np.int16),
                          speech(tmp_path, "What number is on the paper?", "Samantha")])
    messages, _ = asyncio.run(talk(url, pcm, until=done, timeout=60, image=image))
    first, second = final_texts(messages, "assistant")[:2]
    assert "looking" in states(messages)
    assert "MILK" in first.upper() and "42" in second


@pytest.mark.skipif(not shutil.which("claude"), reason="needs Claude Code signed in")
def test_memory_with_claude(server, tmp_path):
    """auto: what you say in one conversation is there in the next one."""
    (tmp_path / "settings.json").write_text(json.dumps({"memory": "auto"}))
    url = server("--mode", "assistant", "--lang", "es", "--llm", "claude", "--tts", "none")
    say = lambda text: speech(tmp_path, text, "Mónica")  # noqa: E731
    pcm = np.concatenate([say("Hey Jarvis"), say("Mi perro se llama Toby."), np.zeros(RATE * 6, np.int16),
                          say("Apágate."), np.zeros(RATE * 30, np.int16),
                          say("Hey Jarvis"), say("¿Cómo se llama mi perro?")])
    memory_file = tmp_path / "memory.json"
    messages, _ = asyncio.run(talk(url, pcm, timeout=40,
                                   until=lambda m: len(final_texts(m, "assistant")) >= 3))
    facts = json.loads(memory_file.read_text())["facts"]
    assert any("Toby" in f for f in facts)
    assert "Toby" in final_texts(messages, "assistant")[-1]


def test_camera_on_the_screen_by_voice(server, tmp_path):
    url = server("--mode", "assistant", "--lang", "es", "--wake", "none", "--llm", "apple")
    pcm = np.concatenate([speech(tmp_path, "Activa la cámara.", "Mónica"), np.zeros(RATE * 3, np.int16),
                          speech(tmp_path, "Apaga la cámara.", "Mónica")])  # after it says «Cámara activada»
    cameras = lambda m: [x["on"] for x in m if x.get("type") == "camera"]  # noqa: E731
    messages, _ = asyncio.run(talk(url, pcm, until=lambda m: len(cameras(m)) >= 2, timeout=20))
    assert cameras(messages) == [True, False]
    assert "asleep" not in states(messages)  # «apaga» is not «apágate»


@pytest.mark.skipif(not shutil.which("claude"), reason="needs Claude Code signed in")
def test_its_own_tools_with_claude(server, tmp_path):
    """In its own words: a setting (with your «yes») and the camera (without)."""
    from PIL import Image

    (tmp_path / "settings.json").write_text(json.dumps({"log_transcripts": True}))
    url = server("--mode", "assistant", "--lang", "es", "--wake", "none", "--llm", "claude", "--tts", "none")
    say = lambda text: speech(tmp_path, text, "Mónica")  # noqa: E731
    pause = np.zeros(RATE * 12, np.int16)
    pcm = np.concatenate([say("Pon la cara redonda, la del orbe."), pause, say("Sí."), pause,
                          say("Enséñame en la pantalla lo que estás viendo.")])
    camera = lambda m: [x for x in m if x.get("type") == "camera"]  # noqa: E731
    messages, _ = asyncio.run(talk(url, pcm, until=camera, timeout=40, image=Image.new("RGB", (320, 240), "gray")))
    assert json.loads((tmp_path / "settings.json").read_text())["face"] == "orb"
    assert {"type": "config"} in messages  # the page changed its face at once
    assert camera(messages) == [{"type": "camera", "on": True}]


@pytest.mark.skipif(not shutil.which("claude"), reason="needs Claude Code signed in")
def test_reads_with_a_full_resolution_photo(server, tmp_path):
    """Small print can't be read in a 320×240 video: asked to read, it takes a photo."""
    import io

    from PIL import Image, ImageDraw, ImageFont

    page = Image.new("RGB", (1600, 1200), "white")
    ImageDraw.Draw(page).text((500, 560), "CODE 7351", fill="black", font=ImageFont.load_default(size=22))
    jpeg = io.BytesIO()
    page.save(jpeg, "JPEG", quality=90)
    (tmp_path / "settings.json").write_text(json.dumps({"eyes": True}))
    url = server("--mode", "assistant", "--lang", "en", "--wake", "none", "--llm", "claude", "--tts", "none")
    messages, _ = asyncio.run(talk(url, speech(tmp_path, "Read the code on this paper.", "Samantha"),
                                   until=lambda m: final_texts(m, "assistant"), timeout=60,
                                   image=page.resize((320, 240)), photo=jpeg.getvalue()))
    assert any(m.get("type") == "photo" for m in messages)
    assert "7351" in final_texts(messages, "assistant")[0].replace(" ", "")
