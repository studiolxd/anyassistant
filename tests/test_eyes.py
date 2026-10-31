import json

import pytest

import eyes
import settings
from plugins.llm_claude.permissions import load


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


def test_read_words(lang):
    yes, no = {"en": ("Read this", "What do you see?"), "es": ("¿Qué pone aquí?", "¿Qué ves?")}[lang.code]
    assert eyes.wants_to_read(yes) and not eyes.wants_to_read(no)


def test_photo_from_the_device(seeing, monkeypatch):
    import asyncio
    import io

    from PIL import Image

    big = io.BytesIO()
    Image.new("RGB", (4000, 3000), "white").save(big, "JPEG")

    def ask(message):
        asyncio.get_running_loop().call_later(0.05, eyes.photo_arrived, message["id"], big.getvalue())
        return True

    monkeypatch.setattr(eyes, "ask_device", ask)
    image = asyncio.run(eyes.photo())
    assert Image.open(io.BytesIO(image)).size == (1568, 1176)  # resized for the LLM
    assert eyes.FRAME.read_bytes() == image


def test_no_photo_in_time(seeing, monkeypatch):
    import asyncio

    monkeypatch.setattr(eyes, "PHOTO_WAIT", 0.1)
    monkeypatch.setattr(eyes, "ask_device", lambda message: True)
    assert asyncio.run(eyes.photo()) is None


def test_hermes_gets_the_image():
    from plugins.llm_hermes import Hermes

    content = Hermes._content("What's this?", b"jpeg")
    assert content[1]["image_url"]["url"].startswith("data:image/jpeg;base64,")
    assert Hermes._content("Hi", None) == "Hi"
