"""How much it says: detail levels, built-in and your own."""

import pytest

import llm
import settings
import tools
from brain.assistant import Assistant
from conftest import load_script


@pytest.fixture
def active(monkeypatch, tmp_path, en):
    monkeypatch.setattr(settings, "PATH", tmp_path / "settings.json")
    monkeypatch.setattr(settings, "active", {"name": "Jarvis"})
    return settings.active


def test_neutral_by_default(active):
    assert "one to three sentences" in llm.instructions()


def test_levels_go_into_the_prompt(active):
    active["detail"] = "concise"
    assert llm.DETAIL_LEVELS["concise"] in llm.instructions()
    active["detail"] = "detailed"
    assert llm.DETAIL_LEVELS["detailed"] in llm.instructions()


def test_your_own_levels(active):
    active["detail_levels"] = {"telegraphic": "Answer in five words or fewer.", "neutral": "Two sentences."}
    active["detail"] = "telegraphic"
    assert "five words or fewer" in llm.instructions()
    active["detail"] = "neutral"
    assert "Two sentences." in llm.instructions()  # changed
    assert set(llm.detail_levels()) == {"concise", "neutral", "detailed", "telegraphic"}


def test_set_detail_by_voice_without_confirmation(active):
    tools.call("set_detail", {"level": "concise"})
    assert settings.load()["detail"] == "concise"
    with pytest.raises(tools.ToolError):
        tools.call("set_detail", {"level": "verbose"})
    assert load_script("jarvis-confirm").describe("mcp__jarvis__set_detail", {"level": "concise"}) is None


def test_a_change_mid_conversation_reaches_the_llm(active):
    a = object.__new__(Assistant)
    a.detail = llm.detail()
    assert a._with_detail("Hi") == "Hi"
    active["detail"] = "concise"
    assert a._with_detail("And tomorrow?").startswith("(From now on: Answer in one short sentence")
    assert a._with_detail("Thanks") == "Thanks"  # said once
