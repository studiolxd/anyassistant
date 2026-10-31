"""bin/anyassistant-confirm and the assistant: writing needs a spoken «yes»."""

import json
import subprocess
import sys
import time

import pytest

import kernel
from conftest import ROOT, load_script

hook = load_script("anyassistant-confirm")


@pytest.mark.parametrize("command", [
    "/x/bin/gog gmail search 'is:unread' --plain",
    "/x/bin/gog calendar events --today",
    "/x/bin/gog gmail send --help",
    "/x/bin/gog help",
])
def test_reading_goes_through(command):
    assert hook.describe("Bash", {"command": command}) is None


def test_writing_is_described():
    assert hook.describe("Bash", {"command": "/x/bin/gog gmail send --to a@b.c"}) == "gmail send --to a@b.c"
    assert hook.describe("mcp__holded__get_invoices", {}) is None
    assert hook.describe("mcp__holded__create_invoice", {"total": 5}) == 'holded: create_invoice {"total": 5}'


def call(project, tool, tool_input):
    data = json.dumps({"tool_name": tool, "tool_input": tool_input})
    return subprocess.run([sys.executable, ROOT / "bin" / "anyassistant-confirm"], input=data,
                          capture_output=True, text=True)


def test_blocks_until_confirmed_then_once(project):
    action = ("mcp__holded__create_invoice", {"total": 5})
    first = call(project, *action)
    assert first.returncode == 2 and "confirmation" in first.stderr
    pending = json.loads((project / ".build" / "confirm" / "pending.json").read_text())
    assert "create_invoice" in pending["action"]

    # What the voice server writes when the user says «yes».
    (project / ".build" / "confirm" / "confirmed.json").write_text(
        json.dumps({"signature": pending["signature"], "until": time.time() + 60}))
    assert call(project, *action).returncode == 0
    assert call(project, *action).returncode == 2  # good for one use only


def test_confirming_another_action_does_not_help(project):
    call(project, "mcp__holded__create_invoice", {"total": 5})
    pending = json.loads((project / ".build" / "confirm" / "pending.json").read_text())
    (project / ".build" / "confirm" / "confirmed.json").write_text(
        json.dumps({"signature": pending["signature"], "until": time.time() + 60}))
    assert call(project, "mcp__holded__create_invoice", {"total": 5000}).returncode == 2


def answer(text):
    """What the plugin does with your sentence while an action waits."""
    return kernel.load("confirmation").answer(text)


@pytest.fixture
def confirm(tmp_path, monkeypatch, en):
    import paths

    monkeypatch.setattr(paths, "CONFIRM", tmp_path)

    def pending(**extra):
        (tmp_path / "pending.json").write_text(json.dumps({"signature": "abc", "action": "x", **extra}))

    return tmp_path, pending


def test_yes_authorizes_for_a_minute(confirm):
    folder, pending = confirm
    pending(at=time.time())
    assert answer("Yes, do it") is False  # the sentence still goes to the LLM
    confirmed = json.loads((folder / "confirmed.json").read_text())
    assert confirmed["signature"] == "abc" and confirmed["until"] > time.time() + 50
    assert not (folder / "pending.json").exists()


def test_anything_else_cancels(confirm):
    folder, pending = confirm
    pending(at=time.time(), consume=True)
    assert answer("No, wait") is True  # resolved by the plugin: not for the LLM
    assert not (folder / "confirmed.json").exists()
    assert not (folder / "pending.json").exists()


def test_old_questions_expire(confirm):
    folder, pending = confirm
    pending(at=time.time() - 300)
    assert not answer("Yes")  # nothing waits any more
    assert not (folder / "confirmed.json").exists()


def test_off_the_hook_lets_everything_through(project):
    (project / "settings.json").write_text(json.dumps({"plugins": {"confirmation": False}}))
    assert call(project, "mcp__holded__create_invoice", {"total": 5}).returncode == 0


def test_off_jarvis_tools_dont_ask(monkeypatch):
    import settings
    import tools

    import paths

    paths.PERMISSIONS.unlink()  # «confirm» on
    monkeypatch.setattr(settings, "active", {"plugins": {"confirmation": False}})
    tools.call("set_name", {"name": "Viernes"})  # no «yes» needed
    assert kernel.load("confirmation").store.pending() is None


def test_a_waiting_question_shows_on_the_face(confirm):
    _, pending = confirm
    assert kernel.load("confirmation").waiting() is None
    pending(at=time.time())
    assert kernel.load("confirmation").waiting()["action"] == "x"
