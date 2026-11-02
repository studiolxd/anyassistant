"""Each room's noise (the ear's NoiseFloor) and its calibration per device (the plugin «calibration»)."""

import asyncio

import numpy as np
import pytest

import hub
import kernel
import paths
import settings
import vad

kernel.load_all()
from plugins.brain_transcriber import ear as ear_module
from plugins.brain_transcriber.ear import Ear, Measurement, NoiseFloor

calibration = kernel.load("calibration")
devices = kernel.load("devices")
WINDOW = ear_module.WINDOW


class FakeVAD:
    """Says what it is told: the next windows' probabilities."""

    def __init__(self):
        self.next = []

    def probability(self, window):
        return self.next.pop(0) if self.next else 0.0

    def reset(self):
        pass


@pytest.fixture(autouse=True)
def clean(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "active", {})
    monkeypatch.setattr(paths, "HOME", tmp_path)
    monkeypatch.setattr(calibration, "FILE", tmp_path / "calibration.json")
    monkeypatch.setattr(calibration, "progress", {})
    monkeypatch.setattr(devices, "FILE", tmp_path / "devices.json")
    monkeypatch.setattr(hub, "sessions", {})
    monkeypatch.setattr(hub, "active", None)
    monkeypatch.setattr(vad, "create", FakeVAD)


def tone(level: float, samples: int = WINDOW) -> np.ndarray:
    """A window at this RMS level."""
    return np.full(samples, level, np.float32)


# --- The noise floor ---

def test_the_floor_follows_the_room_up_slowly_and_down_fast():
    floor = NoiseFloor()
    assert floor.thresholds() == (ear_module.THRESHOLD_ON, ear_module.THRESHOLD_OFF)  # a quiet room: the fixed ones
    for _ in range(30):  # a second of a fan: barely moved yet
        floor.quiet(0.02, 0.4)
    assert floor.level < 0.01 and floor.vad < 0.2
    for _ in range(600):  # twenty seconds: it got there
        floor.quiet(0.02, 0.4)
    assert floor.level == pytest.approx(0.02, abs=0.002) and floor.vad == pytest.approx(0.4, abs=0.02)
    on, off = floor.thresholds()
    assert on == pytest.approx(0.7, abs=0.03) and off == pytest.approx(on * 0.7, abs=0.02)  # stricter now
    for _ in range(40):  # it went quiet: in little more than a second, back
        floor.quiet(0.0, 0.0)
    assert floor.level < 0.004 and floor.vad < 0.06


def test_the_floor_has_a_ceiling_and_can_be_turned_off():
    floor = NoiseFloor()
    for _ in range(2000):
        floor.quiet(0.5, 1.0)  # a vacuum cleaner that the VAD takes for speech
    assert floor.level == ear_module.MAX_LEVEL and floor.thresholds()[0] == ear_module.MAX_ON
    assert not floor.loud(0.01) and floor.loud(0.1)
    settings.active["noise_adapt"] = False
    assert floor.thresholds() == (ear_module.THRESHOLD_ON, ear_module.THRESHOLD_OFF) and floor.loud(0.0)


def test_a_measurement_proposes_thresholds_for_the_room():
    quiet = Measurement(1)
    for _ in range(quiet.wanted):
        quiet.add(tone(0.001), 0.02)
    found = quiet.result()
    assert found["db"] == -60 and (found["on"], found["off"]) == (0.5, 0.35) and not found["talking"]
    noisy = Measurement(1)
    for i in range(noisy.wanted):
        noisy.add(tone(0.03), 0.45 if i % 2 else 0.2)  # a TV: the VAD half believes it
    found = noisy.result()
    assert found["db"] == pytest.approx(-30.5, abs=0.1) and found["on"] == 0.75 and found["off"] == 0.52
    assert not found["talking"]
    talking = Measurement(1)
    for i in range(talking.wanted):
        talking.add(tone(0.1), 0.9 if i % 3 else 0.1)
    assert talking.result()["talking"]


# --- In the ear ---

def ear(states):
    found = Ear(None, on_state=states.append, on_heard=lambda t, ti: None)
    found.awake = True
    return found


def test_the_ear_starts_a_sentence_only_above_the_rooms_noise():
    states = []
    quiet = ear(states)
    quiet.vad.next = [0.6]
    quiet._window(tone(0.05))
    assert quiet.speaking and states == ["hearing"]  # a quiet room: 0.6 is speech
    noisy = ear(states := [])
    noisy.noise.start(level=0.03, vad=0.45)  # calibrated with the TV on: 0.75 to start
    noisy.vad.next = [0.6, 0.8, 0.8]
    noisy._window(tone(0.05))
    assert not noisy.speaking
    noisy._window(tone(0.03))  # believed, but not louder than the room
    assert not noisy.speaking
    noisy._window(tone(0.1))
    assert noisy.speaking and states == ["hearing"]


def test_the_ear_measures_the_room_and_hears_nothing_else_meanwhile():
    states, results = [], []
    found = ear(states)
    found.vad.next = [0.1] * 100
    found.calibrate(0.5, results.append)
    found.hear(np.full(960, 300, np.int16))  # 20 ms at 48 kHz: not enough yet
    assert found.measuring is not None and not results
    for _ in range(30):
        found.hear(np.full(960, 300, np.int16))
    assert found.measuring is None and results and results[0]["seconds"] == 0.5 and not results[0]["talking"]
    assert results[0]["db"] < -30 and not found.speaking and states == []


def test_while_it_speaks_nothing_is_measured():
    found = ear([])
    found.deaf = lambda: True
    found.calibrate(0.1, lambda result: None)
    for _ in range(20):
        found.hear(np.full(960, 300, np.int16))
    assert found.measuring is not None and not found.measuring.levels


# --- The plugin: kept per device, measured from the device, the apps ---

def test_kept_per_device_and_forgotten_with_it():
    result = {"level": 0.01, "db": -40, "vad": 0.3, "on": 0.6, "off": 0.42, "talking": False, "seconds": 3}
    calibration.keep("ipad", result)
    assert calibration.of("ipad")["on"] == 0.6 and calibration.of("mac") is None
    assert calibration.summary("ipad")["noise"] == "some" and calibration.summary("mac") == {}
    assert calibration.noise(-50) == "quiet" and calibration.noise(-20) == "noisy"
    calibration.forget("ipad")
    assert calibration.of("ipad") is None


class Speaker:
    speaking = False


class Brain:
    """What the plugin uses of the assistant (or the transcriber: no «say»)."""

    def __init__(self, says=True):
        self.ear = Ear(None, on_state=lambda s: None, on_heard=lambda t, ti: None)
        self.ear.awake = True
        self.speaker, self.said, self.shown = Speaker(), [], []
        self.sentences = asyncio.Queue()
        if says:
            self.say = self.said.append

    def show_heard(self, text):
        self.shown.append(text)

    def later(self, coroutine):
        asyncio.ensure_future(coroutine)


def feed(brain, probability, level=300, times=40):
    brain.ear.vad.next = [probability] * 200
    for _ in range(times):
        brain.ear.hear(np.full(960, level, np.int16))


async def _calibrate(brain, device, probability, level=300):
    task = asyncio.ensure_future(calibration.run(brain, device))
    for _ in range(20):
        await asyncio.sleep(0.05)
        if brain.ear.measuring is not None:
            break
    feed(brain, probability, level, times=int(calibration.SECONDS * 50) + 5)
    return await task


def test_calibrating_from_a_device_asks_for_silence_says_the_result_and_keeps_it(es):
    brain = Brain()
    result = asyncio.run(_calibrate(brain, "ipad", 0.1, level=30))
    assert result and not result["talking"]
    assert brain.said[0] == "Guarda silencio unos segundos: voy a medir el ruido de la sala."
    assert brain.said[1].startswith("Listo: la sala está en silencio")
    assert calibration.of("ipad")["db"] == result["db"] and calibration.progress["ipad"]["step"] == "done"
    assert brain.ear.noise.level == pytest.approx(result["level"], abs=1e-4)


def test_if_it_heard_talking_nothing_is_kept(es):
    brain = Brain()
    assert asyncio.run(_calibrate(brain, "ipad", 0.9)) is None
    assert brain.said[-1] == "No he podido medir: se oía hablar. Inténtalo en silencio."
    assert calibration.of("ipad") is None and calibration.progress["ipad"]["step"] == "talking"


def test_a_transcriber_without_a_voice_only_measures():
    brain = Brain(says=False)
    assert asyncio.run(_calibrate(brain, "tablet", 0.05, level=30))["db"] < -50
    assert calibration.summary("tablet")["noise"] == "quiet"


def test_the_skill_starts_it_by_voice(es, monkeypatch):
    brain = Brain()
    started = []
    monkeypatch.setattr(calibration, "start", lambda assistant: started.append(assistant) or True)
    assert calibration.Calibrate().hear("Jarvis, calibra el micrófono", brain)
    assert started == [brain] and brain.shown == ["Jarvis, calibra el micrófono"]
    assert not calibration.Calibrate().hear("¿Cómo se calibra el micrófono de una cámara réflex?", brain)
    assert not calibration.Calibrate().hear("¿Qué hora es?", brain)


def test_a_device_that_connects_starts_from_what_its_room_was_like():
    calibration.keep("ipad", {"level": 0.02, "db": -34, "vad": 0.35, "on": 0.65, "off": 0.45})
    brain = Brain()
    session = type("S", (), {"device": "ipad", "brain": brain})()
    calibration._connected(session)
    assert brain.ear.noise.level == 0.02 and brain.ear.noise.thresholds() == (0.65, 0.45)
    other = Brain()
    calibration._connected(type("S", (), {"device": "mac", "brain": other})())
    assert other.ear.noise.thresholds() == (0.5, 0.35)


def test_the_devices_listing_says_each_rooms_noise():
    devices.change("ipad", "iPad", "cocina")
    calibration.keep("ipad", {"level": 0.02, "db": -34, "vad": 0.35, "on": 0.65, "off": 0.46})
    calibration.progress["ipad"] = {"step": "measuring", "at": 0}
    found = devices._listing()[0]["noise"]
    assert found["noise"] == "some" and found["db"] == -34 and found["step"] == "measuring"


def test_the_listing_for_the_apps():
    calibration.keep("ipad", {"level": 0.02, "db": -34, "vad": 0.35, "on": 0.65, "off": 0.46})
    found = calibration._listing()
    assert found["devices"]["ipad"]["noise"] == "some" and found["progress"] == {}


def test_while_measuring_it_says_the_seconds_left(monkeypatch):
    """The apps count the measuring down: its seconds left come with its state."""
    import time

    monkeypatch.setattr(calibration, "progress", {"tablet": {"step": "measuring", "at": time.time() - 1}})
    monkeypatch.setattr(calibration, "of", lambda device: None)
    found = calibration.summary("tablet")
    assert found["step"] == "measuring" and 1.5 < found["left"] <= calibration.SECONDS - 0.9
    monkeypatch.setattr(calibration, "progress", {"tablet": {"step": "asking", "at": time.time()}})
    assert "left" not in calibration.summary("tablet")
