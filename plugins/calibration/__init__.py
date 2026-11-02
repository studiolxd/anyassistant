"""Calibration: the room's noise, per device (each microphone and room differ), so the ear tells
speech from it (plugins/brain-transcriber/ear.py: NoiseFloor, instead of only fixed thresholds).

- On its own, the ear follows each room's noise while it listens; this plugin keeps what each
  device's room is like (calibration.json, by the page's own id: as devices.json), so it starts
  from there when the device connects again, and measures it explicitly:
- «Calibra el micrófono» on a device, «Calibrate» in the Mac's Devices window or the admin page's
  (POST /admin/calibration {"calibrate": device id}): it asks for silence, measures SECONDS of what
  the device hears (not while it speaks), says what it found and keeps it. If it heard talking, it
  says so and keeps nothing. Where each one is, for the apps: GET /admin/calibration («progress»),
  and with each device in GET /devices («noise»).
- «noise_adapt» (on): the thresholds follow the room (and its calibration); off: the fixed ones.
"""

import asyncio
import json
import logging
import time

from aiohttp import web as http

import events
import hub
import i18n
import options
import paths
import web
from options import Option
from skills import Skill, skill
from text import words

log = logging.getLogger("calibration")
FILE = paths.HOME / "calibration.json"
SECONDS = 3  # of silence measured
QUIET = -45  # dBFS: below this the room is quiet; above SOME, noisy
SOME = -30

options.add(Option("noise_adapt", True, "speech detection follows each room's noise, as the device hears it (and "
                   "its calibration, if measured); off: fixed thresholds", "voice", "bool", live=True))

# Where each calibration is, by device, for the apps: asking (for silence), measuring, done or
# talking (it heard someone: nothing kept); kept a while once it ends.
progress: dict[str, dict] = {}


# --- What each device's room is like ---

def load() -> dict:
    """{device id: {"level", "db", "vad", "on", "off", "at"}}."""
    try:
        return json.loads(FILE.read_text())["devices"]
    except (OSError, ValueError, KeyError):
        return {}


def _save(found: dict):
    FILE.parent.mkdir(parents=True, exist_ok=True)
    FILE.write_text(json.dumps({"devices": found}, indent=2))


def of(device: str | None) -> dict | None:
    return load().get(device or "") if device else None


def keep(device: str, result: dict):
    found = load()
    found[device] = {k: result[k] for k in ("level", "db", "vad", "on", "off")} | {"at": time.time()}
    _save(found)


def forget(device: str):
    found = load()
    if found.pop(device, None) is not None:
        _save(found)


def noise(db: float) -> str:
    """How the room is, from its noise in dBFS: quiet, some or noisy."""
    return "quiet" if db < QUIET else "some" if db < SOME else "noisy"


def summary(device: str | None) -> dict:
    """For the apps, with the device: its noise, when it was measured, and the calibration going on."""
    found = {}
    if kept := of(device):
        found = {"noise": noise(kept["db"]), "db": kept["db"], "at": kept["at"]}
    now = time.time()
    if (step := progress.get(device or "")) and (step["step"] in ("asking", "measuring") or now - step["at"] < 60):
        found["step"] = step["step"]
        if step["step"] == "measuring":  # seconds still to measure: the apps count them down
            found["left"] = round(max(0.0, SECONDS - (now - step["at"])), 1)
    return found


@events.on("connected")
def _connected(session):
    """A device connected (again): its ear starts from what its room was like."""
    ear = getattr(session.brain, "ear", None)
    kept = of(session.device)
    if ear is not None and kept:
        ear.noise.start(kept["level"], kept["vad"])


# --- Measuring it ---

def _ear(brain):
    return getattr(brain, "ear", None)


async def _said(brain, most: float = 12):
    """Waits until what it was told to say has been said (and the echo guard after it)."""
    speaker = getattr(brain, "speaker", None)
    if getattr(brain, "tts", None):  # it has a voice: first let it start (synthesizing takes a moment)
        for _ in range(12):
            if getattr(speaker, "speaking", False):
                break
            await asyncio.sleep(0.25)
    for _ in range(int(most / 0.25)):
        await asyncio.sleep(0.25)
        queue = getattr(brain, "sentences", None)
        if (queue is None or queue.empty()) and not getattr(speaker, "speaking", False) and not brain.ear.deaf():
            return


async def run(brain, device: str | None) -> dict | None:
    """Calibrates the device's room from that device: asks for silence, measures, says the result.
    The result, or None if it heard talking (nothing kept) or it couldn't."""
    ear = _ear(brain)
    if ear is None or ear.measuring is not None:
        return None
    key = device or "?"
    progress[key] = {"step": "asking", "at": time.time()}
    if hasattr(brain, "say"):
        brain.say(i18n.L("speech.calibrate_silence"))
        await _said(brain)
    progress[key] = {"step": "measuring", "at": time.time()}
    done = asyncio.get_running_loop().create_future()
    ear.calibrate(SECONDS, lambda result: None if done.done() else done.set_result(result))
    try:
        result = await asyncio.wait_for(done, SECONDS + 20)  # a device that stops sending: not forever
    except asyncio.TimeoutError:
        ear.measuring = None
        progress[key] = {"step": "talking", "at": time.time()}
        log.warning("calibration on %s: no audio", key)
        return None
    if result["talking"]:
        progress[key] = {"step": "talking", "at": time.time()}
        log.info("calibration on %s: it heard talking (VAD p95 %.2f): nothing kept", key, result["vad"])
        if hasattr(brain, "say"):
            brain.say(i18n.L("speech.calibrate_talking"))
        return None
    if device:
        keep(device, result)
    ear.noise.start(result["level"], result["vad"])
    progress[key] = {"step": "done", "at": time.time(), **result}
    log.info("calibrated %s: %s dBFS (%s), VAD %.2f → thresholds %.2f/%.2f", key, result["db"], noise(result["db"]),
             result["vad"], result["on"], result["off"])
    if hasattr(brain, "say"):
        brain.say(i18n.L("speech.calibrate_done", noise=i18n.L(f"calibration.noise.{noise(result['db'])}")))
    return result


def start(brain) -> bool:
    """Starts it on that device, in the background; False if it can't (no ear, or already measuring)."""
    ear = _ear(brain)
    if ear is None or ear.measuring is not None:
        return False
    session = hub.of(brain)
    asyncio.ensure_future(run(brain, session.device if session else None))
    return True


@skill
class Calibrate(Skill):
    order = 14  # before the Mac's commands («abre…») and the timers; after the language, the camera, the LLM
    local = False

    def hear(self, text: str, assistant) -> bool:
        found = words(text)
        said = " ".join(found)
        if len(found) > 6 or not any(phrase in said for phrase in i18n.L.list("calibration.start")):
            return False
        assistant.show_heard(text)
        if not start(assistant):
            assistant.say(i18n.L("speech.calibrate_busy"))
        return True


# --- For the Mac app and the admin page ---

def _listing() -> dict:
    now = time.time()
    for device in [d for d, p in progress.items() if p["step"] in ("done", "talking") and now - p["at"] > 60]:
        progress.pop(device)
    return {"devices": {d: {**kept, "noise": noise(kept["db"])} for d, kept in load().items()}, "progress": progress}


@web.route("GET", "/admin/calibration")
async def _list(request):
    if not web.owner(request):  # this computer, or an admin's browser
        return http.json_response({}, status=403)
    return http.json_response(_listing())


@web.route("POST", "/admin/calibration")
async def _change(request):
    """{"calibrate": device id} starts it on that device (it asks for silence there and says what it
    found); {"forget": device id}. Where each one is: «progress» in the answer (GET too)."""
    if not web.owner(request):
        return http.json_response({}, status=403)
    data = await request.json()
    if "calibrate" in data:
        session = hub.by_device(str(data["calibrate"]))
        if session is None or _ear(session.brain) is None:
            return http.json_response({"error": "that device isn't connected"}, status=400)
        token = hub.here.set(session)
        try:
            if not start(session.brain):
                return http.json_response({"error": "it is already measuring"}, status=400)
        finally:
            hub.here.reset(token)
    elif "forget" in data:
        forget(str(data["forget"]))
    return http.json_response(_listing())
