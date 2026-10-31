import json

import pytest

import eyes
import settings
from llm.permissions import load


@pytest.fixture
def seeing(monkeypatch, tmp_path):
    monkeypatch.setattr(settings, "active", {"eyes": True})
    monkeypatch.setattr(eyes, "FRAME", tmp_path / "eyes" / "now.jpg")
    monkeypatch.setattr(eyes, "source", lambda: b"jpeg")


def test_words_that_mean_looking(lang):
    yes, no = {"en": ("What do you see?", "What time is it?"), "es": ("Léeme esto", "¿Qué hora es?")}[lang.code]
    assert eyes.wants_to_look(yes) and not eyes.wants_to_look(no)


def test_capture_leaves_the_frame_for_claude(seeing):
    assert eyes.capture() == b"jpeg"
    assert eyes.FRAME.read_bytes() == b"jpeg"
    assert str(eyes.FRAME) in eyes.instructions()


def test_off_sees_nothing_and_keeps_nothing(seeing):
    eyes.capture()
    settings.active["eyes"] = False
    assert eyes.capture() is None and not eyes.FRAME.exists()
    assert eyes.instructions() == ""


def test_claude_may_read_only_the_frame(seeing, project):
    p = load(project, project / ".mcp.json")
    args = p.arguments
    assert args[args.index("--tools") + 1] == "Read"
    assert args[args.index("--allowedTools") + 1] == f"Read(/{eyes.FRAME})"


def test_no_eyes_no_read(project, monkeypatch):
    monkeypatch.setattr(settings, "active", {})
    (project / "permissions.json").write_text(json.dumps({"commands": {}}))
    args = load(project, project / ".mcp.json").arguments
    assert args[args.index("--tools") + 1] == ""
