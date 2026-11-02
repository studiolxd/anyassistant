"""The plugin «sounds» (waking and falling asleep) and the alarm's, in skill-alarms."""

import numpy as np

import kernel
import settings
from audio import RATE

themes = kernel.load("page").themes


class Speaker:
    def __init__(self):
        self.played = []

    def play(self, pcm):
        self.played.append(pcm)


def test_two_short_notes_without_clicks_rising_and_falling():
    sounds = kernel.load("sounds")
    wake, sleep = sounds.sound("wake", None), sounds.sound("sleep", None)
    half = int(0.09 * RATE)
    assert len(wake) == len(sleep) == 2 * half
    assert abs(int(wake[0])) < 100 and abs(int(wake[-1])) < 100
    assert np.array_equal(wake[:half], sleep[half:])  # the same notes, the other way round


def test_a_themes_own_sound_wins():
    sounds = kernel.load("sounds")
    assert np.array_equal(sounds.sound("wake", "bedside"), themes.sound("bedside", "wake"))
    assert not np.array_equal(sounds.sound("wake", "eyes"), themes.sound("bedside", "wake"))


def test_off_it_wakes_in_silence(monkeypatch):
    from plugins.brain_transcriber import Transcriber

    ear = Transcriber.__new__(Transcriber)
    ear.speaker = Speaker()
    ear._beep("wake")
    assert len(ear.speaker.played) == 1
    monkeypatch.setattr(settings, "active", {"plugins": {"sounds": False}})
    ear._beep("wake")
    assert len(ear.speaker.played) == 1


def test_the_alarm_rings_even_without_the_sounds_plugin(monkeypatch):
    monkeypatch.setattr(settings, "active", {"plugins": {"sounds": False}})
    alarms = kernel.module("skill-alarms")
    tone = alarms.alarm_sound("eyes")
    assert tone is not None and len(tone) > RATE // 4
    assert np.array_equal(alarms.alarm_sound("bedside"), themes.sound("bedside", "alarm"))


def test_the_apps_ring_with_the_themes_alarm():
    """/alarm.wav: the theme's alarm as the server rings it (sound, silence, again), under 30 s."""
    import io
    import wave

    alarms = kernel.load("skill-alarms")
    with wave.open(io.BytesIO(alarms.ringing("bedside"))) as w:
        assert (w.getnchannels(), w.getsampwidth(), w.getframerate()) == (1, 2, 48000)
        seconds = w.getnframes() / 48000
        pcm = np.frombuffer(w.readframes(w.getnframes()), np.int16)
    assert 20 < seconds <= 30
    tone = alarms.alarm_sound("bedside")
    assert np.array_equal(pcm[:len(tone)], tone)


def test_the_themes_page_hears_each_sound_as_it_plays():
    """/sounds/<kind>.wav: the theme's own, or the system's (X-Theme-Sound says which)."""
    import asyncio
    import io
    import wave

    from aiohttp.test_utils import make_mocked_request

    sounds = kernel.load("sounds")
    kernel.load("skill-alarms")

    def get(kind, theme):
        request = make_mocked_request("GET", f"/sounds/{kind}.wav?theme={theme}", match_info={"kind": kind})
        return asyncio.run(sounds._sound(request))

    own, system = get("alarm", "bedside"), get("wake", "eyes")
    assert own.headers["X-Theme-Sound"] == "1" and system.headers["X-Theme-Sound"] == "0"
    with wave.open(io.BytesIO(system.body)) as w:
        assert np.array_equal(np.frombuffer(w.readframes(w.getnframes()), np.int16), sounds.sound("wake", "eyes"))
    assert get("nope", "eyes").status == 404
