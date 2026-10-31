"""Phase 2: listens and shows what you say on the phone's screen."""

import events
import i18n
import kernel
import settings
from audio import louder


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
        page = kernel.module("page")
        if data.get("type") == "skin" and page and data.get("name") in page.skins.available():
            self.skin = data["name"]  # this device's skin: its sounds
        elif data.get("type") == "tap":
            events.emit("tap", self)  # the screen was tapped (tap-to-wake…)

    def _beep(self, kind: str):
        """Wake or sleep: the plugin «sounds» (the skin's, or its own); silence without it."""
        sounds = kernel.module("sounds")
        pcm = sounds.sound(kind, getattr(self, "skin", None) or settings.get("skin")) if sounds else None
        if pcm is not None:
            self.speaker.play(louder(pcm, volume()))

    def _woke_up(self):
        self._beep("wake")

    def _fell_asleep(self, by_command: bool):
        self._beep("sleep")
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
