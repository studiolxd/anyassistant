"""Its own voice heard back (server/echo.py: envelopes, the trail of what it sent, the judge), and
listening while it speaks (the ear with «listen_while_speaking»)."""

import asyncio
import time

import numpy as np
import pytest
from scipy.signal import lfilter

import echo
import kernel
import settings
import vad

kernel.load_all()
from plugins.brain_transcriber import ear as ear_module
from plugins.brain_transcriber.ear import Ear

RATE = 48000
SEED = 7


@pytest.fixture(autouse=True)
def clean(monkeypatch):
    monkeypatch.setattr(settings, "active", {})


# --- Synthetic speech: noise with a syllabic loudness pattern (what an envelope sees of a voice) ---

def speechlike(seconds: float, seed: int, rate: int = RATE, syllables: float = 4.0) -> np.ndarray:
    """Noise whose loudness rises and falls like syllables (a random pattern per seed), -1…1."""
    rng = np.random.default_rng(seed)
    t = np.arange(int(seconds * rate)) / rate
    count = max(1, int(seconds * syllables))
    gains = rng.uniform(0.2, 1.0, count)
    centers = (np.arange(count) + rng.uniform(0.3, 0.7, count)) / syllables
    env = np.zeros_like(t)
    for g, c in zip(gains, centers):
        env += g * np.exp(-((t - c) ** 2) / (2 * (0.06 ** 2)))
    return (env * rng.standard_normal(len(t)) * 0.3).astype(np.float32)


def through_the_room(pcm: np.ndarray, delay: float, loss_db: float, rate: int = RATE, seed: int = 1) -> np.ndarray:
    """What a microphone hears of what the device played: later, quieter, duller (a one-pole
    low-pass), with the room's own noise; after the device's echo cancellation left a residue."""
    rng = np.random.default_rng(seed)
    gain = 10 ** (-loss_db / 20)
    dull = lfilter([0.2], [1, -0.8], pcm) * gain
    late = np.concatenate([np.zeros(int(delay * rate), np.float32), dull]).astype(np.float32)
    return late + rng.standard_normal(len(late)).astype(np.float32) * 0.002


def to16(pcm48: np.ndarray) -> np.ndarray:
    return pcm48[::3].astype(np.float32)


def int16(pcm: np.ndarray) -> np.ndarray:
    return np.clip(pcm * 32767, -32768, 32767).astype(np.int16)


# --- Envelopes and correlation ---

def test_the_envelope_is_fifty_values_a_second_floored():
    env = echo.envelope(np.zeros(RATE, np.float32), RATE)
    assert len(env) == 50 and np.all(env == echo.FLOOR)
    loud = echo.envelope(np.full(RATE, 0.5, np.float32), RATE)
    assert loud[0] == pytest.approx(-6.0, abs=0.1)
    assert len(echo.envelope(int16(np.full(960, 0.5)), RATE)) == 1  # int16 is scaled


def test_correlation_of_the_same_quieter_and_of_another():
    a = echo.envelope(speechlike(2, 1), RATE)
    assert echo.correlation(a, a) == pytest.approx(1.0)
    assert echo.correlation(a, a - 20) == pytest.approx(1.0)  # 20 dB quieter: the same shape
    assert echo.correlation(echo.amplitude(a), echo.amplitude(a - 20)) == pytest.approx(1.0)
    assert echo.correlation(a, echo.envelope(speechlike(2, 2), RATE)) < 0.4
    assert echo.correlation(a, np.full(len(a), -30.0)) == 0.0  # flat: nothing to compare


# --- The trail of what it sent ---

def test_the_trail_keeps_a_timeline_with_gaps_and_cuts():
    trail = echo.Trail()
    trail.add(int16(np.full(RATE, 0.5)), 100.0)  # a second from t=100
    trail.add(int16(np.full(RATE, 0.5)), 102.0)  # another from t=102: a silent second between
    assert trail.start == 100.0 and trail.end == pytest.approx(103.0)
    window = trail.window(99.5, 103.5)
    assert len(window) == 200
    assert np.all(window[:25] == echo.FLOOR) and np.all(window[25:75] > -7) and np.all(window[75:125] == echo.FLOOR)
    assert trail.playing(100.0, 101.0) and not trail.playing(101.0, 102.0)
    trail.cut(102.5)  # stopped half way through the second one
    assert trail.end == pytest.approx(102.5)
    trail.add(int16(np.full(RATE, 0.5)), 200.0)  # much later: the old trail goes
    assert trail.start == 200.0 and len(trail.frames) == 50


def test_the_trail_keeps_only_the_last_seconds():
    trail = echo.Trail()
    for i in range(20):
        trail.add(int16(np.full(RATE, 0.3)), 50.0 + i)
    # KEEP seconds before the last one started (now, for it), and all of that one
    assert trail.start == pytest.approx(69 - echo.KEEP) and trail.end == pytest.approx(70)


def test_an_onset_is_silence_then_loud():
    trail = echo.Trail()
    trail.add(int16(np.full(RATE, 0.5)), 10.0)
    assert trail.onset(10.5) and trail.onset(10.0 + echo.ONSET_SECONDS - 0.05)
    assert not trail.onset(10.0 + echo.ONSET_SECONDS + 0.3)  # it has been playing a while
    trail.add(int16(np.full(RATE, 0.5)), 11.0)  # it goes on: no new onset
    assert not trail.onset(11.5)


# --- The judge: its echo, or a person over it ---

def scene(seed_out: int, seed_in: int | None, loss_db: float = 20, delay: float = 0.25, person_db: float = 0):
    """What a device played (seed_out) and what its microphone sent back: the residue of that, plus
    a person (seed_in) talking over it if given; (trail, audio heard at 16 kHz, when it ended)."""
    out = speechlike(2.0, seed_out)
    trail = echo.Trail()
    start = 1000.0
    trail.add(int16(out), start)
    heard = through_the_room(out, delay, loss_db)
    if seed_in is not None:
        person = speechlike(2.0, seed_in) * 10 ** (person_db / 20)
        heard = heard[:len(person)] + person[:len(heard)]
    ended = start + len(heard) / RATE
    return trail, to16(heard), ended


def judge_for(*trails):
    return echo.Judge(lambda: list(trails))


def test_its_own_echo_matches_and_the_lag_is_found():
    trail, heard, ended = scene(1, None, delay=0.25)
    judge = judge_for(trail)
    assert judge.is_echo(heard, ended)
    score, lag = judge.last
    assert score > 0.9 and lag == pytest.approx(0.25, abs=0.06)  # the room's filter smears it a little


@pytest.mark.parametrize("loss_db", [10, 20, 30])  # the residue of its voice after the device's echo cancellation
def test_however_quiet_the_residue_it_still_matches(loss_db):
    trail, heard, ended = scene(3, None, loss_db=loss_db)
    assert judge_for(trail).is_echo(heard, ended)


def test_a_person_talking_over_it_does_not_match():
    trail, heard, ended = scene(1, 2)
    judge = judge_for(trail)
    assert not judge.is_echo(heard, ended)
    assert judge.last[0] < echo.THRESHOLD


def test_a_person_alone_after_it_stopped_does_not_match():
    trail = echo.Trail()
    trail.add(int16(speechlike(2.0, 5)), 1000.0)
    person = speechlike(2.0, 6)
    assert not judge_for(trail).is_echo(to16(person), 1005.0)  # nothing was playing under it: not judged


def test_the_other_devices_output_counts_too():
    mine, other = echo.Trail(), echo.Trail()
    _, heard, ended = scene(4, None)
    other.add(int16(speechlike(2.0, 4)), 1000.0)  # the one playing was the other device in the room
    assert judge_for(mine, other).is_echo(heard, ended)


def test_the_threshold_is_a_setting():
    trail, heard, ended = scene(1, 2)
    settings.active["echo_match"] = 0.05
    assert judge_for(trail).is_echo(heard, ended)  # anything goes now


def test_numbers_for_the_report():
    """Not a check: the scores for echo, for a person over it, and the margin, printed with -s."""
    rows = []
    for seed in range(1, 9):
        trail, heard, ended = scene(seed, None)
        j = judge_for(trail)
        j.is_echo(heard, ended)
        rows.append(("echo", seed, j.last[0]))
        trail, heard, ended = scene(seed, seed + 20)
        j.is_echo(heard, ended)
        rows.append(("person+echo", seed, j.last[0]))
        trail, heard, ended = scene(seed, seed + 40, person_db=-6)
        j.is_echo(heard, ended)
        rows.append(("quiet person+echo", seed, j.last[0]))
    print()
    for kind in ("echo", "person+echo", "quiet person+echo"):
        scores = [s for k, _, s in rows if k == kind]
        print(f"{kind:20} min {min(scores):.2f}  median {np.median(scores):.2f}  max {max(scores):.2f}")
    assert min(s for k, _, s in rows if k == "echo") > max(s for k, _, s in rows if k == "person+echo")


# --- The ear while it speaks ---

class FakeVAD:
    def __init__(self):
        self.next = []

    def probability(self, window):
        return self.next.pop(0) if self.next else 0.0

    def reset(self):
        pass


class FakeJudge:
    def __init__(self, echo=False, onset=False):
        self.echo, self.start, self.asked = echo, onset, 0

    def is_echo(self, audio, end):
        self.asked += 1
        return self.echo

    def onset(self):
        return self.start


def make_ear(monkeypatch, deaf=False):
    monkeypatch.setattr(vad, "create", FakeVAD)
    states, heard = [], []
    ear = Ear(stt=None, on_state=states.append, on_heard=lambda text, timings: heard.append((text, timings)),
              deaf=lambda: deaf)
    ear.awake = True
    return ear, states


def speak(ear, windows: int, probability: float):
    """Feeds `windows` VAD windows (32 ms each) of this speech probability."""
    ear.vad.next = [probability] * windows
    ear.hear(np.full(ear_module.WINDOW * 3 * windows, 1000, np.int16))


def test_deaf_while_it_speaks_unless_listening_through(monkeypatch):
    ear, states = make_ear(monkeypatch, deaf=True)
    ear.echo = FakeJudge()
    speak(ear, 20, 0.9)
    assert not ear.speaking  # deaf: nothing starts
    settings.active["listen_while_speaking"] = True
    speak(ear, 20, 0.9)
    assert ear.speaking and ear.over  # it hears, knowing it was speaking


def test_its_echo_is_dropped_and_a_person_over_it_is_transcribed(monkeypatch):
    settings.active["listen_while_speaking"] = True
    ear, states = make_ear(monkeypatch, deaf=True)
    ear.echo = FakeJudge(echo=True)
    sent = []
    monkeypatch.setattr(ear, "_transcribe", lambda audio, over=False: sent.append(over) or _done())

    async def go():  # the ear starts the transcription as a task
        speak(ear, 20, 0.9)
        speak(ear, 25, 0.0)  # 0.8 s of silence: the sentence ends
        assert ear.echo.asked == 1 and not sent and states[-1] == "listening"
        ear.echo = FakeJudge(echo=False)
        speak(ear, 20, 0.9)
        speak(ear, 25, 0.0)
        assert sent == [True]  # transcribed, marked as said over it
    asyncio.run(go())


def test_talked_over_it_stops_before_transcribing(monkeypatch):
    """A person over it stops it as the sentence ends, even if what was said doesn't transcribe."""
    settings.active["listen_while_speaking"] = True
    ear, _ = make_ear(monkeypatch, deaf=True)
    overs = []
    ear.on_over = lambda: overs.append(True)
    monkeypatch.setattr(ear, "_transcribe", lambda audio, over=False: _done())

    async def go():
        ear.echo = FakeJudge(echo=True)
        speak(ear, 20, 0.9)
        speak(ear, 25, 0.0)
        assert not overs  # its echo: nothing
        ear.echo = FakeJudge(echo=False)
        speak(ear, 20, 0.9)
        speak(ear, 25, 0.0)
        assert overs == [True]
    asyncio.run(go())


def test_in_between_its_words_decide(monkeypatch):
    """Not clearly a person (some likeness to its output): no stop before transcribing."""
    settings.active["listen_while_speaking"] = True
    ear, _ = make_ear(monkeypatch, deaf=True)
    overs, sent = [], []
    ear.on_over = lambda: overs.append(True)
    monkeypatch.setattr(ear, "_transcribe", lambda audio, over=False: sent.append(over) or _done())
    ear.echo = FakeJudge(echo=False)
    ear.echo.clearly_a_person = lambda: False

    async def go():
        speak(ear, 20, 0.9)
        speak(ear, 25, 0.0)
        assert not overs and sent == [True]  # transcribed: _heard decides by its words
    asyncio.run(go())


def test_the_judge_tells_a_clear_person():
    judge = echo.Judge(lambda: [])
    assert judge.clearly_a_person()  # nothing judged
    judge.last = (0.3, 0.2)
    assert judge.clearly_a_person()
    judge.last = (0.65, 0.2)
    assert not judge.clearly_a_person()


async def _done():
    pass


def test_an_onset_of_its_output_vetoes_a_start(monkeypatch):
    settings.active["listen_while_speaking"] = True
    ear, _ = make_ear(monkeypatch, deaf=True)
    ear.echo = FakeJudge(onset=True)
    speak(ear, 20, 0.9)
    assert not ear.speaking
    ear.echo.start = False
    speak(ear, 20, 0.9)
    assert ear.speaking


def test_the_assistant_stops_when_talked_over(monkeypatch):
    from plugins.brain_assistant import Assistant

    class Speaker:
        speaking, last_sound = True, time.time()

    class Turn:
        def locked(self):
            return False

    a = object.__new__(Assistant)
    a.said, a.saying, a.speaker, a.turn = [], "the weather tomorrow is sunny".split(), Speaker(), Turn()
    stopped, handled = [], []
    monkeypatch.setattr(Assistant, "stop", lambda self: stopped.append(True))
    monkeypatch.setattr(Assistant, "_handle", lambda self, text, timings: handled.append(text))
    monkeypatch.setattr(kernel, "module", lambda name: None)
    a._heard("Tomorrow is sunny", {"over": True, "stt_ms": 100, "audio_s": 1})  # its own words: an echo
    assert not stopped and not handled
    a._heard("What about Friday?", {"over": True, "stt_ms": 100, "audio_s": 1})
    assert stopped and handled == ["What about Friday?"]


def test_a_long_answer_sent_at_once_keeps_what_plays_now():
    """The whole answer is queued at once: what plays now isn't dropped for what plays later (KEEP
    counted from now, not from the end of what was queued)."""
    trail = echo.Trail()
    rng = np.random.default_rng(1)
    start = t0 = 1000.0
    for seconds in (12.0, 1.5, 9.0, 8.0):
        trail.add((rng.normal(0, 1, int(48000 * seconds)) * 8000).astype(np.int16), start, now=t0)
        start += seconds
    assert trail.playing(t0 + 1, t0 + 3.5) and trail.playing(t0 + 28, t0 + 30)
