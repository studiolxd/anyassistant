"""The plugin «sounds» (waking and falling asleep) and the alarm's, in skill-alarms."""

import numpy as np

import kernel
import settings
import skins
from audio import RATE


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


def test_a_skins_own_sound_wins():
    sounds = kernel.load("sounds")
    assert np.array_equal(sounds.sound("wake", "bedside"), skins.sound("bedside", "wake"))
    assert not np.array_equal(sounds.sound("wake", "eyes"), skins.sound("bedside", "wake"))


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
    assert np.array_equal(alarms.alarm_sound("bedside"), skins.sound("bedside", "alarm"))
