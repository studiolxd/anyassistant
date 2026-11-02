"""«transcribe»: listens and shows what you say on the device's screen. Its Ear
(ear.py: wake word, VAD, speech recognition) is how the assistant listens too."""

import logging
import os

import events
import hub
import i18n
import kernel
import settings
import stt
import wake
from audio import louder
from brain import register

log = logging.getLogger("brain")


def volume() -> float:
    """Settings «volume» (5–100 %) as a factor."""
    return max(5, min(100, settings.get("volume") or 100)) / 100


def listening(args):
    """What it listens with, from the settings: the STT engine (warmed up), a function that makes a
    wake word for each session (it keeps state; None: no wake word) and the Ear's options."""
    engine = stt.create(args.stt, language=i18n.L.stt_language, model=args.stt_model)
    log.info("loading STT %s (%s)…", engine.name, engine.model)
    engine.warm_up()
    wake_factory = None
    if args.wake != "none":
        wake_options = {"word": args.wake_word}
        if args.threshold is not None:
            wake_options["threshold"] = args.threshold
        log.info("wake word: %s", wake.create(args.wake, **wake_options).phrase)
        wake_factory = lambda: wake.create(args.wake, **wake_options)  # noqa: E731
    record = None
    if args.record:  # true: a WAV per session in the cache (an older path still works)
        import paths

        record = args.record if isinstance(args.record, str) else str(paths.CACHE / "recordings" / "session.wav")
        os.makedirs(os.path.dirname(record), exist_ok=True)
    ear = {"record": record, "silence": args.silence, "follow_up": args.follow_up}
    return engine, wake_factory, ear


@register("transcribe")
class Transcriber:
    @classmethod
    def create(cls, args):
        engine, wake_factory, ear = listening(args)
        return lambda speaker, send: cls(engine, wake_factory() if wake_factory else None, speaker, send, ear)

    def __init__(self, stt, wake, speaker, send, ear=None, deaf=None, on_interrupt=None, busy=None):
        self.send = send
        self.speaker = speaker
        self.wake = wake
        from .ear import Ear

        self.ear = Ear(
            stt,
            on_state=self._state,
            on_heard=self._heard,
            wake=wake,
            on_wake=self._woke_up,
            on_sleep=self._fell_asleep,
            deaf=deaf,
            on_interrupt=on_interrupt,
            busy=busy,
            may_wake=lambda why: hub.claim(self, self.ear.level, why),
            **(ear or {}),
        )

    def _heard(self, text: str, timings: dict):
        self.send({"type": "text", "text": text, "timings": timings})

    def on_message(self, data: dict):
        page = kernel.module("page")
        if data.get("type") == "theme" and page and data.get("name") in page.themes.available():
            self.theme = data["name"]  # this device's theme: its sounds
        elif data.get("type") == "tap":
            events.emit("tap", self)  # the screen was tapped (tap-to-wake…)

    def _beep(self, kind: str):
        """Wake or sleep: the plugin «sounds» (the theme's, or its own); silence without it."""
        sounds = kernel.module("sounds")
        pcm = sounds.sound(kind, getattr(self, "theme", None) or settings.get("theme")) if sounds else None
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
