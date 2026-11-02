"""Every plugin is found, and listing them doesn't load heavy libraries."""

import sys

import pytest
from conftest import here

import llm
import stt
import tts
import vad
import wake


@pytest.mark.parametrize("registry, expected", [  # {engine: its plugin}
    (stt, {"parakeet": "stt-parakeet", "mlx-whisper": "stt-mlx-whisper"}),
    (wake, {"whisper": "wake-whisper", "openwakeword": "wake-openwakeword"}),
    (llm, {"claude": "llm-claude", "apple": "llm-apple", "hermes": "llm-openai", "openai": "llm-openai"}),
    (tts, {"avspeech": "tts-avspeech", "macos": "tts-macos", "kokoro": "tts-kokoro", "piper": "tts-piper"}),
    (vad, {"silero": "vad-silero"}),
])
def test_plugins_are_registered(registry, expected):
    """Each engine whose plugin fits this computer (the Mac's only on the Mac)."""
    assert {name for name, plugin in expected.items() if here(plugin)} <= set(registry.available())


def test_listing_does_not_import_models():
    for registry in (stt, wake, llm, tts, vad):
        registry.available()
    assert not {"mlx_whisper", "parakeet_mlx", "openwakeword", "torch", "piper", "kokoro_onnx"} & sys.modules.keys()


def test_unknown_plugin():
    with pytest.raises(ValueError, match="Available"):
        stt.create("nope")
