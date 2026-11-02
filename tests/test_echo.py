"""Its own voice leaking back into the microphone is dropped, your answers are not."""

import time

import kernel

kernel.load_all()  # plugins.* importable
from plugins.brain_assistant import ECHO_WINDOW, Assistant


class Speaker:
    def __init__(self, ago):
        self.last_sound = time.time() - ago


def assistant(said, ago=0.5):
    a = object.__new__(Assistant)  # skips __init__: no STT, LLM or voice
    a.said, a.saying, a.speaker = said.split(), [], Speaker(ago)
    return a


TIMINGS = {"stt_ms": 100, "audio_s": 0.5}


def test_a_piece_of_what_it_said_is_echo():
    assert assistant("do you need anything else")._is_echo("Anything else?", TIMINGS)


def test_other_words_are_not():
    assert not assistant("do you need anything else")._is_echo("What time is it?", TIMINGS)


def test_long_sentences_are_not():
    said = "i can send it to the whole team right now if you want"
    assert not assistant(said)._is_echo("Send it to the whole team right now", TIMINGS)


def test_late_repetitions_are_your_answer():
    a = assistant("delete only the two promotional ones", ago=ECHO_WINDOW + 3)
    assert not a._is_echo("Only the two promotional ones", TIMINGS)


def test_its_own_name_is_not_an_interruption(monkeypatch):
    a = assistant("")
    a.saying = "por cierto yo soy jarvis no gabriela".split()
    stopped = []
    monkeypatch.setattr(Assistant, "stop", lambda self: stopped.append(True))
    assert not a._interrupt("Yo soy Jarvis.")
    assert a._interrupt("Jarvis, para.") and stopped
