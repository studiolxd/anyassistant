import json

import pytest

import kernel

eyes = kernel.load("eyes")
import settings
from plugins.llm_claude.permissions import load


@pytest.fixture
def seeing(monkeypatch, tmp_path):
    monkeypatch.setattr(settings, "active", {"plugins": {"eyes": True}})
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
    settings.active["plugins"] = {"eyes": False}
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
    from plugins.llm_openai import Hermes

    content = Hermes._content("What's this?", b"jpeg")
    assert content[1]["image_url"]["url"].startswith("data:image/jpeg;base64,")
    assert Hermes._content("Hi", None) == "Hi"


def test_every_llm_that_sees_knows_its_left_is_the_users_right(monkeypatch):
    monkeypatch.setattr(eyes, "enabled", lambda: True)
    assert "user's right" in eyes.instructions() and str(eyes.FRAME) in eyes.instructions()  # Claude
    assert "user's right" in eyes.seeing() and str(eyes.FRAME) not in eyes.seeing()  # Hermes: no Read tool


def test_claudes_read_of_a_missing_frame_asks_for_a_photo_first(tmp_path, monkeypatch):
    """The Mac sends no frames: when Claude opens the camera's file, the hook asks for a photo."""
    import io
    import sys

    import paths
    from conftest import load_script

    look = load_script("anyassistant-look")
    monkeypatch.setattr(paths, "EYES", tmp_path)
    asked = []
    monkeypatch.setattr(look.urllib.request, "urlopen", lambda request, timeout: asked.append(
        (request.full_url, request.data)) or io.BytesIO(b"{}"))
    monkeypatch.setattr(sys, "argv", ["anyassistant-look", "mac1"])

    def read(path):
        monkeypatch.setattr(sys, "stdin", io.StringIO(json.dumps({"tool_name": "Read", "tool_input": {"file_path": path}})))
        look.main()

    read("/Users/me/notes.txt")  # another file: nothing
    assert asked == []
    read(str(tmp_path / "now.jpg"))  # the camera's, missing: a photo from that device
    assert asked[0][0].endswith("/eyes/now") and json.loads(asked[0][1]) == {"device": "mac1"}
    (tmp_path / "now.jpg").write_bytes(b"jpeg")
    read(str(tmp_path / "now.jpg"))  # already there (frames come): nothing
    assert len(asked) == 1
