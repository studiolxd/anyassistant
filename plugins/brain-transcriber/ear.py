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

Each room is different: the VAD's thresholds aren't only the fixed ones but follow the room's
noise as this device's microphone hears it (NoiseFloor), and a calibration (the plugin
«calibration»: a few seconds of silence measured on the device, Measurement) sets where it starts.

Paused (pause/resume): while another app uses the device's microphone (a call) nothing is heard
and the face says so. While it speaks it is deaf, unless «listen_while_speaking»: then sentences
are segmented as always and, at the end, its own echo is told from a person by loudness
(server/echo.py) and dropped; a person talking over it reaches on_heard with timings «over».
"""

import asyncio
import logging
import time
import wave
from concurrent.futures import ThreadPoolExecutor

import numpy as np
from scipy.signal import resample_poly

import i18n
import kernel
import vad
import settings
from stt import RATE

log = logging.getLogger("ear")

WINDOW = 512  # samples at 16 kHz, what Silero expects
THRESHOLD_ON = 0.5  # speech probability to start a sentence (in a quiet room; NoiseFloor raises it)
THRESHOLD_OFF = 0.35  # below this counts as silence
OFF_RATIO = THRESHOLD_OFF / THRESHOLD_ON  # «off» follows «on» when the noise raises it
MAX_ON = 0.85  # however noisy the room, a sentence can still start
MARGIN = 0.3  # how far above what the noise itself scores on the VAD a sentence has to be
SNR = 1.5  # how much louder than the noise floor (RMS) a window must be to start a sentence (~3.5 dB)
RISE = 0.005  # the floor follows the room up slowly (per 32 ms window: ~6 s)…
FALL = 0.05  # …and down fast (~0.6 s): a sentence shouldn't be lost because a fan stopped
MAX_LEVEL = 0.05  # the loudest the floor can go (-26 dBFS): a loud room never gates speech out
SILENCE = 0.6  # seconds of silence that end a sentence (--silence)
MINIMUM = 0.2  # minimum seconds of speech to transcribe (a «hola» is ~0.3)
MAXIMUM = 15  # maximum seconds of a sentence
PRE_ROLL = 0.3  # audio kept from before speech is detected (so the start isn't lost)
FOLLOW_UP = 20  # seconds without speech (since it spoke or heard you) before sleeping (--follow-up)
LEVEL_SECONDS = 1.5  # how loud it heard its name: the loudest of the last seconds (devices compare it)

_thread = ThreadPoolExecutor(max_workers=1, thread_name_prefix="stt")


def rms(window) -> float:
    return float(np.sqrt(np.mean(np.square(window)))) if window is not None and len(window) else 0.0


def decibels(level: float) -> float:
    """An RMS level (0–1) in dBFS."""
    return round(float(20 * np.log10(max(level, 1e-6))), 1)


class NoiseFloor:
    """The room's noise as this device's microphone hears it, so speech is told from it by more
    than fixed thresholds: how loud the background is (`level`: the RMS of the windows that
    weren't speech) and how much the VAD believes that noise is speech (`vad`). It follows the
    room: up slowly (a fan, the TV), down fast (it went quiet). A calibration (the plugin
    «calibration») sets where it starts, per device: `start(level, vad)`.

    - thresholds(): the VAD probabilities that start a sentence and that count as silence: the
      fixed ones, raised by what the noise itself scores (plus MARGIN), up to MAX_ON.
    - loud(rms): whether a window stands above the noise (SNR): a sentence needs it to start.
    With settings «noise_adapt» off, the fixed thresholds and nothing else.
    """

    def __init__(self, level: float = 0.0, vad: float = 0.0):
        self.level = level
        self.vad = vad

    def start(self, level: float, vad: float):
        """Where it starts: a calibration of this device (or what it knew when it last connected)."""
        self.level, self.vad = min(MAX_LEVEL, float(level)), float(vad)

    @staticmethod
    def adapting() -> bool:
        return settings.get("noise_adapt", True) is not False

    def quiet(self, loudness: float, probability: float):
        """A window that wasn't speech: the floor follows it, slowly up and quickly down."""
        self.level = min(MAX_LEVEL, self.level + (loudness - self.level) * (RISE if loudness > self.level else FALL))
        self.vad += (probability - self.vad) * (RISE if probability > self.vad else FALL)

    @staticmethod
    def proposal(vad: float) -> tuple[float, float]:
        """The thresholds for a room whose noise scores `vad` on the VAD: (on, off)."""
        on = min(MAX_ON, max(THRESHOLD_ON, vad + MARGIN))
        return round(on, 2), round(on * OFF_RATIO, 2)

    def thresholds(self) -> tuple[float, float]:
        if not self.adapting():
            return THRESHOLD_ON, THRESHOLD_OFF
        return self.proposal(self.vad)

    def loud(self, loudness: float) -> bool:
        """Whether this window stands above the room's noise."""
        return not self.adapting() or self.level <= 0 or loudness >= self.level * SNR


class Measurement:
    """A calibration: `seconds` of what the device hears while nobody talks, window by window
    (the ear feeds it; Ear.calibrate). Its result(): the noise level (RMS and dBFS), what the VAD
    makes of it (its 95th percentile), the thresholds that follow, and whether it heard talking
    (then it isn't a measure of the room: the plugin asks again)."""

    TALKING = 0.2  # more than this share of windows the VAD takes for speech: someone talked

    def __init__(self, seconds: float, done=None):
        self.wanted = max(1, int(seconds * RATE / WINDOW))
        self.levels: list[float] = []
        self.probabilities: list[float] = []
        self.done = done or (lambda result: None)

    def add(self, window: np.ndarray, probability: float):
        self.levels.append(rms(window))
        self.probabilities.append(float(probability))

    @property
    def full(self) -> bool:
        return len(self.levels) >= self.wanted

    def result(self) -> dict:
        levels, probabilities = np.array(self.levels), np.array(self.probabilities)
        level = float(np.sqrt(np.mean(np.square(levels)))) if len(levels) else 0.0
        vad = float(np.percentile(probabilities, 95)) if len(probabilities) else 0.0
        on, off = NoiseFloor.proposal(vad)
        return {"level": round(level, 5), "db": decibels(level), "vad": round(vad, 3), "on": on, "off": off,
                "talking": bool(len(probabilities)) and float(np.mean(probabilities >= THRESHOLD_ON)) > self.TALKING,
                "seconds": round(len(levels) * WINDOW / RATE, 1)}


class Ear:
    def __init__(
        self, stt, on_state, on_heard, wake=None, on_wake=None, on_sleep=None,
        deaf=None, record=None, silence=SILENCE, follow_up=FOLLOW_UP, on_interrupt=None,
        busy=None, may_wake=None, noise=None,
    ):
        self.stt = stt
        self.wake = wake
        self.on_state = on_state
        self.on_heard = on_heard
        self.on_wake = on_wake or (lambda: None)
        self.on_sleep = on_sleep or (lambda by_command: None)
        self.vad = vad.create()
        self.noise = noise or NoiseFloor()  # this device's room: its thresholds
        self.measuring = None  # a calibration going on (Measurement): it gets every window meanwhile
        self.pending = np.zeros(0, dtype=np.float32)
        self.pre_roll = []
        self.sentence = []
        self.speaking = False
        self.silence = 0.0
        self.speech = 0.0  # seconds of speech within the sentence
        self.awake = wake is None or kernel.enabled("always-on")  # always on: awake from the start
        self.last_activity = 0.0  # to fall asleep after `follow_up`
        self.end_of_sentence = silence  # seconds of silence that end a sentence
        self.follow_up = follow_up
        self.busy = busy or (lambda: False)  # thinking or ringing: not idle
        # Whether this voice may wake it (its wake word's audio): the plugin «voices», through
        # the assistant; None: anyone.
        self.voice_may_wake = None
        # While the speaker is talking it doesn't listen, or it would hear itself;
        # only for the wake word, to be interrupted («Jarvis, stop»): on_interrupt(text)
        # says whether to stop (False: it was its own voice saying its name).
        self.deaf = deaf or (lambda: False)
        self.on_interrupt = on_interrupt
        # Whether it may wake up (why None: its name, how loud it heard it in `level`): with
        # several devices, only one answers (hub.claim).
        self.may_wake = may_wake or (lambda why: True)
        self.levels = []  # loudness of the last chunks
        self.generation = 0  # a wake-up undone (drop) discards what it was still transcribing
        self.last_audio = None  # the 16 kHz audio of the last sentence heard
        self.interruptible = False  # the wake word is listening while it speaks
        # Paused: another app uses the device's microphone (a call), so what arrives isn't heard
        # (it isn't the room, or it isn't ours to hear). By who says so: the device («paused»
        # messages), the server (the plugin «microphone-busy») or the audio itself (exact zeros,
        # stream-api): each with its reason and, if known, the app. Any of them pauses it.
        self.paused: dict[str, tuple[str, str]] = {}
        self.paused_at = 0.0
        # Its own voice, heard back (settings «listen_while_speaking»): an echo.Judge that says
        # whether a sentence heard while it spoke is its echo (dropped) or someone talking over it,
        # and whether its output just started (a chime: not a sentence). None: deaf while it speaks.
        self.echo = None
        self.over = False  # the sentence being heard overlaps its own speech
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
        if self.paused:
            return "paused"
        if self.wake is None:
            return "listening"
        return "awake" if self.awake else "asleep"

    # --- Paused: another app uses the microphone ---

    PAUSE_SOURCES = ("device", "server", "zeros")  # whose reason is shown, in this order

    def pause(self, why: str = "microphone", app: str = "", source: str = "device"):
        """Stops hearing (what arrives is discarded, nothing wakes it) until resume(): another app
        uses the device's microphone (`why`: microphone, call or interrupted; `app` if known)."""
        was = bool(self.paused)
        self.paused[source] = (why or "microphone", app or "")
        if was:
            self.on_state("paused")  # the reason shown may have changed
            return
        log.info("paused: %s%s (%s)", why, f" by {app}" if app else "", source)
        self.paused_at = time.time()
        self._reset()
        if self.wake:
            self.wake.reset()
        self.on_state("paused")

    def resume(self, source: str | None = None):
        """Hears again: that source's reason is over (None: every one). The follow-up clock didn't
        run meanwhile: a conversation isn't lost to a call."""
        if not self.paused:
            return
        if source is None:
            self.paused.clear()
        else:
            self.paused.pop(source, None)
        if self.paused:
            self.on_state("paused")
            return
        log.info("listening again (paused %.0f s)", time.time() - self.paused_at)
        self.last_activity += time.time() - self.paused_at
        self._reset()
        self.on_state(self.idle_state)

    @property
    def pause_reason(self) -> tuple[str, str]:
        """Why it is paused and by which app, if known: (why, app); ('', '') if it isn't."""
        for source in self.PAUSE_SOURCES:
            if source in self.paused:
                return self.paused[source]
        return next(iter(self.paused.values()), ("", ""))

    def through(self) -> bool:
        """Whether it keeps hearing while it speaks (settings «listen_while_speaking»), telling its
        own echo from a person by loudness (echo.Judge)."""
        return self.echo is not None and bool(settings.get("listen_while_speaking"))

    def hear(self, pcm48: np.ndarray):
        audio = resample_poly(pcm48.astype(np.float32) / 32768, 1, 3).astype(np.float32)
        if self.recording:
            self.recording.writeframes((np.clip(audio, -1, 1) * 32767).astype(np.int16).tobytes())
        if self.paused:  # another app's call: not heard, not even for its name
            return
        if len(audio):  # how loud it hears now (devices compare it: hub.claim)
            self.levels = (self.levels + [rms(audio)])[-int(LEVEL_SECONDS * RATE / len(audio)):]
        if self.measuring is not None:  # calibrating: it only measures (not while it speaks)
            if not self.deaf():
                self._measure(audio)
            return
        if self.wake and (not self.awake or self.wake.continuous):
            heard = self.wake.listen(audio) and not self.deaf()
            if not self.awake:
                if heard:
                    sentence = getattr(self.wake, "heard_sentence", None)
                    if not self.may_wake(None):  # another device answers
                        self.wake.heard_sentence = None
                        self.wake.reset()
                        return
                    said = getattr(self.wake, "wake_audio", None)
                    if self.voice_may_wake and said is not None and not self.voice_may_wake(said):
                        self.wake.heard_sentence = None  # not a known voice: it doesn't wake
                        self.wake.reset()
                        return
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
                if not self.through():  # its name is the only thing it hears while it speaks
                    return
            elif self.interruptible:  # it finished speaking: what the word half heard is forgotten
                self.interruptible = False
                self.wake.reset()
        self.pending = np.concatenate([self.pending, audio])
        while len(self.pending) >= WINDOW:
            window, self.pending = self.pending[:WINDOW], self.pending[WINDOW:]
            self._window(window)

    def calibrate(self, seconds: float, done) -> Measurement:
        """Measures the room for `seconds` (while nobody talks; not while it speaks) and calls
        done(result); meanwhile nothing else is heard (the plugin «calibration»)."""
        self._reset()
        self.measuring = Measurement(seconds, done)
        return self.measuring

    def _measure(self, audio: np.ndarray):
        self.pending = np.concatenate([self.pending, audio])
        while len(self.pending) >= WINDOW and self.measuring is not None:
            window, self.pending = self.pending[:WINDOW], self.pending[WINDOW:]
            self.measuring.add(window, self.vad.probability(window))
            if self.measuring.full:
                found, self.measuring = self.measuring, None
                self._reset()
                found.done(found.result())

    def _interrupted(self):
        sentence = getattr(self.wake, "heard_sentence", None)
        self.wake.heard_sentence = None
        said = getattr(self.wake, "wake_audio", None)
        if self.voice_may_wake and said is not None and not self.voice_may_wake(said):
            self.wake.reset()  # «Eva, para» by a voice that isn't known: it goes on
            return
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
        """Wakes it up as its name would (a tap…); False if it wasn't asleep (or it is paused)."""
        if not self.wake or self.awake or self.paused or not self.may_wake(why):
            return False
        self._wake_up(why)
        return True

    @property
    def level(self) -> float:
        """How loud it hears (its name, you): the loudest of the last LEVEL_SECONDS."""
        return max(self.levels, default=0.0)

    def _wake_up(self, why: str | None = None):
        log.info("awake (%s): conversation mode", why or self.wake.phrase)
        prepare = getattr(self.stt, "prepare", None)
        if prepare:  # the speech model, if it left memory, starts coming back before the sentence ends
            prepare()
        self._reset()
        self.awake = True
        self.last_activity = time.time()
        self.on_state("awake")
        self.on_wake()

    def sleep(self, reason: str):
        """Goes to sleep because it was told to («go to sleep»: the plugin skill-sleep)."""
        self._sleep(reason, by_command=True)

    def sleep_for(self, reason: str):
        """Goes to sleep as after a silence (another device woke up: the conversation is there now)."""
        self._sleep(reason)

    def drop(self, reason: str):
        """Undoes a wake-up that wasn't for it (another device heard the same word louder):
        asleep again without its sound, and what it was transcribing is discarded."""
        if not self.wake or not self.awake:
            return
        log.info("asleep again: %s", reason)
        self.generation += 1
        self._reset()
        self.awake = False
        self.wake.reset()
        self.on_state("asleep")

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
        on, off = self.noise.thresholds()  # this room's, not only the fixed ones
        deaf = self.deaf()
        if deaf:
            self.last_activity = time.time()  # its own speech counts as activity too
            if not self.through():  # while it speaks it would hear itself: deaf
                self._reset()
                return
            if self.speaking:
                self.over = True  # its voice came in during this sentence: judged at the end
            elif self.echo.onset():
                return  # its own sound just started (a chime, a sentence): not someone talking
        if self.busy():  # thinking an answer, a tool running, an alarm ringing
            self.last_activity = time.time()

        if not self.speaking:
            follow_up = settings.get("follow_up") or self.follow_up
            if self.wake and time.time() - self.last_activity > follow_up and not kernel.enabled("always-on"):
                self._sleep(f"{follow_up:g} s without speech")
                return
            self.pre_roll.append(window)
            self.pre_roll = self.pre_roll[-int(PRE_ROLL * RATE / WINDOW):]
            loudness = rms(window)
            if probability >= on and self.noise.loud(loudness):
                self.speaking = True
                self.over = deaf
                self.sentence = list(self.pre_roll)
                self.silence = 0.0
                self.speech = WINDOW / RATE
                self.on_state("hearing")
            else:
                self.noise.quiet(loudness, probability)  # the room, as it is now
            return

        self.sentence.append(window)
        if probability < off:
            self.silence += WINDOW / RATE
        else:
            self.silence = 0.0
            self.speech += WINDOW / RATE
        duration = len(self.sentence) * WINDOW / RATE
        if self.silence >= self.end_of_sentence or duration >= MAXIMUM:
            audio = np.concatenate(self.sentence)
            speech, over = self.speech, self.over
            self._reset()
            self.last_activity = time.time()
            if speech < MINIMUM:
                log.info("dropped: too short (%.2f s of speech)", speech)
                self.on_state(self.idle_state)
                return
            if over and self.echo is not None and self.echo.is_echo(audio, time.time()):
                log.info("dropped: its own voice (%.2f s)", duration)  # by its loudness: not transcribed
                self.on_state(self.idle_state)
                return
            asyncio.ensure_future(self._transcribe(audio, over))

    def _reset(self):
        self.speaking = False
        self.over = False
        self.sentence = []
        self.pre_roll = []
        self.pending = np.zeros(0, dtype=np.float32)
        self.silence = 0.0
        self.speech = 0.0
        self.vad.reset()

    async def _transcribe(self, audio: np.ndarray, over: bool = False):
        self.on_state("transcribing")
        start = time.time()
        generation = self.generation
        text = await asyncio.get_running_loop().run_in_executor(_thread, self.stt.transcribe, audio)
        if generation != self.generation:  # the wake-up was undone meanwhile: not for it
            return
        timings = {
            "audio_s": round(len(audio) / RATE, 2),
            "stt_ms": round((time.time() - start) * 1000),
        }
        if over:
            timings["over"] = True  # said while it spoke (and it wasn't its echo): an interruption
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
        self.last_audio = audio  # who said it (the plugin «voices») is in it
        self.on_heard(text, timings)
        self.on_state(self.idle_state)
