"""The whisper wake word's matching, without loading Whisper."""

import pytest

import i18n

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
    word.prompt = i18n.L("wake.whisper_prompt", name="Jarvis")
    return word


def test_strip_the_wake_word(jarvis):
    assert jarvis.strip("Hey Jarvis, what time is it?") == "what time is it?"
    assert jarvis.strip("Oye, Yarvis: ¿qué hora es?") == "¿qué hora es?"
    assert jarvis.strip("G&J Arbis, hello") == "hello"


def test_only_among_the_first_words(jarvis):
    text = "I was telling my friend about Jarvis yesterday"
    assert jarvis.strip(text) == text


def test_its_own_prompt_is_noise(lang, jarvis):
    jarvis.prompt = i18n.L("wake.whisper_prompt", name="Jarvis")
    assert jarvis.is_prompt(jarvis.prompt)
    assert jarvis.is_prompt(" ".join(jarvis.prompt.split()[1:]))  # a piece of it


@pytest.mark.parametrize("text", ["Jarvis.", "Hey Jarvis", "Oye Jarvis, ¿qué hora es?", ""])
def test_what_you_say_is_not_the_prompt(lang, jarvis, text):
    jarvis.prompt = i18n.L("wake.whisper_prompt", name="Jarvis")
    assert not jarvis.is_prompt(text)
