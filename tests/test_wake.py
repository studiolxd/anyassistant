"""The whisper wake word's matching, without loading Whisper."""

import pytest

import i18n

from plugins.wake_whisper import SIMILARITY, WhisperWakeWord, phonetic, similarity


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


def test_whole_words_are_not_joined(jarvis):
    """«llama» + «Jarvis» contains «Jarvis»: that is not the word split in two."""
    assert jarvis._position(["strips", "se", "llama", "jarvis"]) is None
    assert jarvis._position(["g", "j", "arbis"]) is not None


def test_only_among_the_first_words(jarvis):
    text = "I was telling my friend about Jarvis yesterday"
    assert jarvis.strip(text) == text


def test_its_own_prompt_is_noise(lang, jarvis):
    jarvis.prompt = i18n.L("wake.whisper_prompt", name="Jarvis")
    assert jarvis.is_prompt(jarvis.prompt)
    assert jarvis.is_prompt(" ".join(jarvis.prompt.split()[1:]))  # a piece of it


def test_variations_of_its_prompt_are_noise(jarvis):
    i18n.use("es")
    jarvis.prompt = i18n.L("wake.whisper_prompt", name="Jarvis")
    assert jarvis.is_prompt("Strips se llama Jarvis.")
    i18n.use("en")
    jarvis.prompt = i18n.L("wake.whisper_prompt", name="Jarvis")
    assert jarvis.is_prompt("The robot's name is Jarvis.")


@pytest.mark.parametrize("text", ["Jarvis.", "Hey Jarvis", "Oye Jarvis, ¿qué hora es?", "Hola, Jarvis", ""])
def test_what_you_say_is_not_the_prompt(lang, jarvis, text):
    jarvis.prompt = i18n.L("wake.whisper_prompt", name="Jarvis")
    assert not jarvis.is_prompt(text)
