"""Every plugin is found, and listing them doesn't load heavy libraries."""

import sys

import pytest

import llm
import stt
import tts
import vad
import wake


@pytest.mark.parametrize("registry, expected", [
    (stt, {"parakeet", "mlx-whisper"}),
    (wake, {"whisper", "openwakeword"}),
    (llm, {"claude", "apple", "hermes"}),
    (tts, {"avspeech", "macos"}),
    (vad, {"silero"}),
])
def test_plugins_are_registered(registry, expected):
    assert expected <= set(registry.available())


def test_listing_does_not_import_models():
    for registry in (stt, wake, llm, tts, vad):
        registry.available()
    assert not {"mlx_whisper", "parakeet_mlx", "openwakeword", "torch"} & sys.modules.keys()


def test_unknown_plugin():
    with pytest.raises(ValueError, match="Available"):
        stt.create("nope")
