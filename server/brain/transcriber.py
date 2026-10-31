"""Phase 2: listens and shows what you say on the phone's screen."""

import i18n
import settings
from audio import beep
from brain.ear import Ear


def create(stt, wake=None, ear=None):
    """Returns the brain(speaker, send) factory that Session expects.

    wake is a function that creates a new WakeWord (one per session, since it
    keeps state) or None to listen without a wake word. ear holds options for
    Ear: record, silence, idle_timeout.
    """

    def brain(speaker, send):
        return Transcriber(stt, wake() if wake else None, speaker, send, ear)

    return brain


class Transcriber:
    def __init__(self, stt, wake, speaker, send, ear=None, deaf=None, on_interrupt=None):
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
            **(ear or {}),
        )

    def _heard(self, text: str, timings: dict):
        self.send({"type": "text", "text": text, "timings": timings})

    def _woke_up(self):
        if settings.get("beeps", True):
            self.speaker.play(beep())

    def _fell_asleep(self, by_command: bool):
        if settings.get("beeps", True):
            self.speaker.play(beep(falling=True))
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
