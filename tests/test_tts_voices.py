"""The voice engines' voices: what each lists without loading its model, the one someone means
(«pon la voz de Dora»), set_voice with Kokoro's and Piper's, and the settings' list. Piper speaking
(it downloads a voice) only with -m e2e."""

import json

import numpy as np
import pytest

import kernel
import settings
import tools
import tts
from plugins.tts_kokoro import VOICES, KokoroVoice
from plugins.tts_piper import PiperTTS


@pytest.fixture
def engine(monkeypatch):
    """Chooses the engine in use (its class, whether it fits this computer or not)."""
    def use(found):
        monkeypatch.setattr(tts, "engine", lambda name=None: found)
    return use


@pytest.fixture
def env(tmp_path, monkeypatch, es):
    kernel.load("tools-system")
    monkeypatch.setattr(settings, "PATH", tmp_path / "settings.json")
    monkeypatch.setattr(settings, "active", {"name": "Jarvis", "tts": "kokoro"})
    monkeypatch.setattr(tools, "requested", set())
    return tmp_path


def saved(env):
    return json.loads((env / "settings.json").read_text())


def test_kokoro_lists_its_voices_by_language_without_loading():
    assert KokoroVoice.voices("es") == ["ef_dora", "em_alex", "em_santa"]  # the language's default first
    english = KokoroVoice.voices("en")
    assert english[0] == "af_heart" and {"bf_emma", "am_michael"} <= set(english) and "ef_dora" not in english
    assert KokoroVoice.label("ef_dora") == "Dora" and KokoroVoice.label("jf_gongitsune") == "Gongitsune"


def test_piper_lists_its_voices_by_language_without_loading():
    spanish = PiperTTS.voices("es")
    assert spanish[0] == "es_ES-davefx-medium" and "es_MX-claude-high" in spanish
    assert all(v.startswith("es_") for v in spanish) and PiperTTS.voices("en")[0] == "en_US-lessac-medium"
    assert PiperTTS.label("es_MX-claude-high") == "Claude" and PiperTTS.label("es_ES-carlfm-x_low") == "Carlfm"


def test_a_voice_it_doesnt_have_is_the_languages_default(es):
    assert PiperTTS("Mónica").voice == "es_ES-davefx-medium"  # the Mac's: nothing loaded nor downloaded
    assert PiperTTS("es_MX-ald-medium").voice == "es_MX-ald-medium"
    assert KokoroVoice("Mónica").voice == "ef_dora"


def test_the_voice_someone_means(engine, es):
    engine(KokoroVoice)
    assert tts.find("Dora") == tts.find("dora") == tts.find("ef_dora") == tts.find("Dora (ef_dora)") == "ef_dora"
    assert tts.find("Heart") is None  # English, not Spanish
    assert tts.find("Heart", "en") == "af_heart"
    engine(PiperTTS)
    assert tts.find("claude") == "es_MX-claude-high" and tts.find("Daniela") == "es_AR-daniela-high"
    engine(None)
    assert tts.find("Dora") is None and tts.voices() == []


def test_set_voice_with_kokoro(env, engine):
    engine(KokoroVoice)
    tools.call("set_voice", {"voice": "Alex"})
    assert saved(env)["voice"] == {"es": "em_alex"}
    with pytest.raises(tools.ToolError, match="Dora"):  # it says which there are
        tools.call("set_voice", {"voice": "Heart"})
    assert "Dora (ef_dora)" in tools.call("get_settings", {})


def test_set_voice_with_piper_keeps_the_other_languages(env, engine):
    engine(PiperTTS)
    settings.save(voice={"en": "en_GB-alba-medium"})
    tools.call("set_voice", {"voice": "Claude"})
    assert saved(env)["voice"] == {"en": "en_GB-alba-medium", "es": "es_MX-claude-high"}


def test_set_voice_without_an_engine(env, engine):
    engine(None)
    with pytest.raises(tools.ToolError, match="no voice engine"):
        tools.call("set_voice", {"voice": "Dora"})


def test_the_settings_list_the_engine_in_uses_voices(env, engine):
    engine(KokoroVoice)
    admin = kernel.load("admin")
    found = {o.name: o for o in __import__("options").OPTIONS}
    listed = admin._voices(found["voice"])
    assert listed[0] == {"name": "ef_dora", "label": "Dora", "language": "es"} and len(listed) == 3
    assert admin._voices(found["rate"]) is None
    assert admin._current(found["voice"]) == "ef_dora"  # empty: Kokoro's own, not the Mac's «Mónica»
    engine(None)
    assert admin._voices(found["voice"]) is None


@pytest.mark.e2e
def test_piper_speaks(es):
    """A real voice (downloaded the first time, ~63 MB, and checked): Spanish, at 48 kHz, faster with a rate."""
    voice = tts.create("piper", voice="Mónica")
    audio = voice.synthesize("Son las cinco y media.")
    assert audio.dtype == np.int16 and 0.6 < len(audio) / tts.RATE < 3 and np.abs(audio).max() > 1000
    faster = tts.create("piper", rate=260).synthesize("Son las cinco y media.")
    assert len(faster) < len(audio)


@pytest.mark.e2e
def test_kokoros_list_is_its_voices_file():
    """VOICES (listed without the model) is what the pinned voices file has."""
    import models

    place = models.fetch("kokoro")
    assert sorted(np.load(place / "voices-v1.0.bin").files) == sorted(VOICES)
