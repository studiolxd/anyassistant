"""Ear: wake word, Silero VAD and transcription through plugins.

Receives 48 kHz PCM in 20 ms chunks and downsamples it to 16 kHz.

- With a wake word: asleep, it only listens for the word. When it hears it, it
  enters conversation mode: transcribes sentence by sentence until it hears the
  sleep command (locale commands.sleep, e.g. «go to sleep», «apágate») or
  `follow_up` seconds pass without speech (since it last spoke or heard you), and
  goes back to sleep: after that, its name again.
- Without a wake word: always awake, transcribes everything that is speech.

Sentences are delimited by the VAD plugin (vad/) in 512-sample windows (32 ms) and transcribed
in a separate thread; the result goes to on_heard(text, timings).
"""

import asyncio
import logging
import time
import wave
from concurrent.futures import ThreadPoolExecutor

import numpy as np
from scipy.signal import resample_poly

import i18n
import vad
import settings
from stt import RATE

log = logging.getLogger("ear")

WINDOW = 512  # samples at 16 kHz, what Silero expects
THRESHOLD_ON = 0.5  # speech probability to start a sentence
THRESHOLD_OFF = 0.35  # below this counts as silence
SILENCE = 0.6  # seconds of silence that end a sentence (--silence)
MINIMUM = 0.2  # minimum seconds of speech to transcribe (a «hola» is ~0.3)
MAXIMUM = 15  # maximum seconds of a sentence
PRE_ROLL = 0.3  # audio kept from before speech is detected (so the start isn't lost)
FOLLOW_UP = 20  # seconds without speech (since it spoke or heard you) before sleeping (--follow-up)

_thread = ThreadPoolExecutor(max_workers=1, thread_name_prefix="stt")


class Ear:
    def __init__(
        self, stt, on_state, on_heard, wake=None, on_wake=None, on_sleep=None,
        deaf=None, record=None, silence=SILENCE, follow_up=FOLLOW_UP, on_interrupt=None,
        busy=None,
    ):
        self.stt = stt
        self.wake = wake
        self.on_state = on_state
        self.on_heard = on_heard
        self.on_wake = on_wake or (lambda: None)
        self.on_sleep = on_sleep or (lambda by_command: None)
        self.vad = vad.create()
        self.pending = np.zeros(0, dtype=np.float32)
        self.pre_roll = []
        self.sentence = []
        self.speaking = False
        self.silence = 0.0
        self.speech = 0.0  # seconds of speech within the sentence
        self.awake = wake is None
        self.last_activity = 0.0  # to fall asleep after `follow_up`
        self.end_of_sentence = silence  # seconds of silence that end a sentence
        self.follow_up = follow_up
        self.busy = busy or (lambda: False)  # thinking or ringing: not idle
        # While the speaker is talking it doesn't listen, or it would hear itself;
        # only for the wake word, to be interrupted («Jarvis, stop»): on_interrupt(text)
        # says whether to stop (False: it was its own voice saying its name).
        self.deaf = deaf or (lambda: False)
        self.on_interrupt = on_interrupt
        self.interruptible = False  # the wake word is listening while it speaks
        self.recording = None  # WAV with everything that arrives, for debugging
        if record:
            # One file per session: reconnecting doesn't overwrite it.
            record = record.removesuffix(".wav") + time.strftime("-%H%M%S.wav")
            self.recording = wave.open(record, "wb")
            self.recording.setnchannels(1)
            self.recording.setsampwidth(2)
            self.recording.setframerate(RATE)
            log.info("recording what arrives to %s", record)

    @property
    def idle_state(self) -> str:
        if self.wake is None:
            return "listening"
        return "awake" if self.awake else "asleep"

    def hear(self, pcm48: np.ndarray):
        audio = resample_poly(pcm48.astype(np.float32) / 32768, 1, 3).astype(np.float32)
        if self.recording:
            self.recording.writeframes((np.clip(audio, -1, 1) * 32767).astype(np.int16).tobytes())
        if self.wake and (not self.awake or self.wake.continuous):
            heard = self.wake.listen(audio) and not self.deaf()
            if not self.awake:
                if heard:
                    sentence = getattr(self.wake, "heard_sentence", None)
                    self._wake_up()
                    if sentence is not None:
                        # "Hey Jarvis, what time is it?" in one go.
                        self.wake.heard_sentence = None
                        asyncio.ensure_future(self._transcribe(sentence))
                return
        elif self.wake and self.awake and self.on_interrupt and settings.get("voice_interrupt", True):
            if self.deaf():
                self.interruptible = True
                if self.wake.listen(audio):
                    self._interrupted()
                return
            if self.interruptible:  # it finished speaking: what the word half heard is forgotten
                self.interruptible = False
                self.wake.reset()
        self.pending = np.concatenate([self.pending, audio])
        while len(self.pending) >= WINDOW:
            window, self.pending = self.pending[:WINDOW], self.pending[WINDOW:]
            self._window(window)

    def _interrupted(self):
        sentence = getattr(self.wake, "heard_sentence", None)
        self.wake.heard_sentence = None
        if not self.on_interrupt(getattr(self.wake, "last_text", "")):
            return
        log.info("interrupted by voice")
        self.interruptible = False
        self.wake.reset()
        self._reset()
        self.last_activity = time.time()
        if sentence is not None:  # «Jarvis, and tomorrow?»: a new question
            asyncio.ensure_future(self._transcribe(sentence))

    def wake_up(self, why: str) -> bool:
        """Wakes it up as its name would (a tap…); False if it wasn't asleep."""
        if not self.wake or self.awake:
            return False
        self._wake_up(why)
        return True

    def _wake_up(self, why: str | None = None):
        log.info("awake (%s): conversation mode", why or self.wake.phrase)
        self._reset()
        self.awake = True
        self.last_activity = time.time()
        self.on_state("awake")
        self.on_wake()

    def sleep(self, reason: str):
        """Goes to sleep because it was told to («go to sleep»: the plugin skill-sleep)."""
        self._sleep(reason, by_command=True)

    def _sleep(self, reason: str, by_command: bool = False):
        if not self.wake or not self.awake:
            return
        log.info("going to sleep: %s", reason)
        self._reset()
        self.awake = False
        self.wake.reset()
        self.on_sleep(by_command)
        self.on_state("asleep")

    def _window(self, window: np.ndarray):
        probability = self.vad.probability(window)
        if self.deaf():
            self._reset()
            self.last_activity = time.time()  # its own speech counts as activity too
            return
        if self.busy():  # thinking an answer, a tool running, an alarm ringing
            self.last_activity = time.time()

        if not self.speaking:
            follow_up = settings.get("follow_up") or self.follow_up
            if self.wake and time.time() - self.last_activity > follow_up:
                self._sleep(f"{follow_up:g} s without speech")
                return
            self.pre_roll.append(window)
            self.pre_roll = self.pre_roll[-int(PRE_ROLL * RATE / WINDOW):]
            if probability >= THRESHOLD_ON:
                self.speaking = True
                self.sentence = list(self.pre_roll)
                self.silence = 0.0
                self.speech = WINDOW / RATE
                self.on_state("hearing")
            return

        self.sentence.append(window)
        if probability < THRESHOLD_OFF:
            self.silence += WINDOW / RATE
        else:
            self.silence = 0.0
            self.speech += WINDOW / RATE
        duration = len(self.sentence) * WINDOW / RATE
        if self.silence >= self.end_of_sentence or duration >= MAXIMUM:
            audio = np.concatenate(self.sentence)
            speech = self.speech
            self._reset()
            self.last_activity = time.time()
            if speech < MINIMUM:
                log.info("dropped: too short (%.2f s of speech)", speech)
                self.on_state(self.idle_state)
                return
            asyncio.ensure_future(self._transcribe(audio))

    def _reset(self):
        self.speaking = False
        self.sentence = []
        self.pre_roll = []
        self.pending = np.zeros(0, dtype=np.float32)
        self.silence = 0.0
        self.speech = 0.0
        self.vad.reset()

    async def _transcribe(self, audio: np.ndarray):
        self.on_state("transcribing")
        start = time.time()
        text = await asyncio.get_running_loop().run_in_executor(_thread, self.stt.transcribe, audio)
        timings = {
            "audio_s": round(len(audio) / RATE, 2),
            "stt_ms": round((time.time() - start) * 1000),
        }
        self.last_activity = time.time()
        if text and hasattr(self.wake, "strip"):
            text = self.wake.strip(text)
            if not text:  # only the wake word was said
                self.on_state(self.idle_state)
                return
        if not text or any(h in text.lower() for h in i18n.L.list("stt.hallucinations")):
            log.info("dropped: «%s» %s", settings.private(text), timings)
            self.on_state(self.idle_state)
            return
        log.info("«%s» %s", settings.private(text), timings)
        self.on_heard(text, timings)
        self.on_state(self.idle_state)
