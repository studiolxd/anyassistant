"""How much it says: detail levels, built-in and your own."""

import pytest

import llm
import settings
import tools
import kernel

kernel.load_all()  # plugins.* importable
from plugins.brain_assistant import Assistant
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
    assert load_script("anyassistant-confirm").describe("mcp__jarvis__set_detail", {"level": "concise"}) is None


def test_a_change_mid_conversation_reaches_the_llm(active):
    a = object.__new__(Assistant)
    a.detail = llm.detail()
    assert a._with_detail("Hi") == "Hi"
    active["detail"] = "concise"
    assert a._with_detail("And tomorrow?").startswith("(From now on: Answer in one short sentence")
    assert a._with_detail("Thanks") == "Thanks"  # said once


def test_jarvis_creates_and_removes_levels(active):
    tools.call("add_detail_level", {"name": "Teacher", "instruction": "Explain it step by step with an example."})
    assert settings.load()["detail_levels"] == {"teacher": "Explain it step by step with an example."}
    active["detail_levels"] = settings.load()["detail_levels"]
    tools.call("set_detail", {"level": "teacher"})
    active["detail"] = "teacher"
    assert "step by step" in llm.instructions()
    tools.call("remove_detail_level", {"name": "teacher"})
    assert settings.load()["detail"] == "neutral"  # it was in use
    assert settings.load()["detail_levels"] == {}


def test_built_in_levels(active):
    tools.call("add_detail_level", {"name": "neutral", "instruction": "Two sentences at most."})
    assert "back to the built-in" in tools.call("remove_detail_level", {"name": "neutral"})
    with pytest.raises(tools.ToolError):
        tools.call("remove_detail_level", {"name": "concise"})


@pytest.mark.parametrize("name, instruction", [("", "Explain it well."), ("a" * 40, "Explain it well."),
                                               ("ok", "short"), ("../x", "Explain it step by step.")])
def test_bad_levels(active, name, instruction):
    with pytest.raises(tools.ToolError):
        tools.call("add_detail_level", {"name": name, "instruction": instruction})


def test_creating_a_level_needs_your_yes():
    assert {"add_detail_level", "remove_detail_level"} <= tools.NEEDS_YES and "set_detail" not in tools.NEEDS_YES
