"""Phase 2: listens and shows what you say on the phone's screen."""

import i18n
import settings
import skins
from audio import beep, louder


def volume() -> float:
    """Settings «volume» (5–100 %) as a factor."""
    return max(5, min(100, settings.get("volume") or 100)) / 100
from brain.ear import Ear


def create(stt, wake=None, ear=None):
    """Returns the brain(speaker, send) factory that Session expects.

    wake is a function that creates a new WakeWord (one per session, since it
    keeps state) or None to listen without a wake word. ear holds options for
    Ear: record, silence, follow_up.
    """

    def brain(speaker, send):
        return Transcriber(stt, wake() if wake else None, speaker, send, ear)

    return brain


class Transcriber:
    def __init__(self, stt, wake, speaker, send, ear=None, deaf=None, on_interrupt=None, on_stop=None, busy=None):
        self.send = send
        self.speaker = speaker
        self.wake = wake
        self.ear = Ear(
            stt,
            on_state=self._state,
            on_heard=self._heard,
            wake=wake,
            on_wake=self._woke_up,
            on_sleep=self._fell_asleep,
            deaf=deaf,
            on_interrupt=on_interrupt,
            on_stop=on_stop,
            busy=busy,
            **(ear or {}),
        )

    def _heard(self, text: str, timings: dict):
        self.send({"type": "text", "text": text, "timings": timings})

    def on_message(self, data: dict):
        if data.get("type") == "skin" and data.get("name") in skins.available():
            self.skin = data["name"]  # this device's skin: its sounds

    def _sound(self, kind: str, default):
        own = skins.sound(getattr(self, "skin", None) or settings.get("skin"), kind)
        return louder(own if own is not None else default, volume())

    def _woke_up(self):
        if settings.get("beeps", True):
            self.speaker.play(self._sound("wake", beep()))

    def _fell_asleep(self, by_command: bool):
        if settings.get("beeps", True):
            self.speaker.play(self._sound("sleep", beep(falling=True)))
        if by_command:
            self.send({"type": "text", "text": i18n.L("speech.goodbye"), "author": "assistant"})

    def _state(self, state: str):
        message = {"type": "state", "state": state}
        if self.wake:
            message["wake_phrase"] = self.wake.phrase
        self.send(message)

    def on_connect(self):
        self._state(self.ear.idle_state)

    def hear(self, pcm):
        self.ear.hear(pcm)
