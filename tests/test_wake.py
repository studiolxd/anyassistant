"""The whisper wake word's matching, without loading Whisper."""

import pytest

from wake.whisper import SIMILARITY, WhisperWakeWord, phonetic, similarity


@pytest.mark.parametrize("heard", ["Jarvis", "Yarvis", "Harvis", "Llarvis", "Jarbis"])
def test_sounds_like_jarvis(heard):
    assert similarity(phonetic(heard.lower()), phonetic("jarvis")) >= SIMILARITY


@pytest.mark.parametrize("heard", ["ya veis", "carlos", "service"])
def test_does_not_sound_like_jarvis(heard):
    assert similarity(phonetic(heard.replace(" ", "")), phonetic("jarvis")) < SIMILARITY


@pytest.fixture
def jarvis():
    word = object.__new__(WhisperWakeWord)  # skips __init__, which loads the models
    word.keys, word.threshold = ["jarvis"], SIMILARITY
    return word


def test_strip_the_wake_word(jarvis):
    assert jarvis.strip("Hey Jarvis, what time is it?") == "what time is it?"
    assert jarvis.strip("Oye, Yarvis: ¿qué hora es?") == "¿qué hora es?"
    assert jarvis.strip("G&J Arbis, hello") == "hello"


def test_only_among_the_first_words(jarvis):
    text = "I was telling my friend about Jarvis yesterday"
    assert jarvis.strip(text) == text
