"""bin/jarvis-confirm and the assistant: writing needs a spoken «yes»."""

import json
import subprocess
import sys
import time

import pytest

from brain import assistant
from conftest import load_script

hook = load_script("jarvis-confirm")


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
    return subprocess.run([sys.executable, project / "bin" / "jarvis-confirm"], input=data,
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


class Fake:
    """Just enough of Assistant to try _confirm."""
    _confirm = assistant.Assistant._confirm


@pytest.fixture
def confirm(tmp_path, monkeypatch, en):
    monkeypatch.setattr(assistant, "CONFIRM", tmp_path)

    def pending(**extra):
        (tmp_path / "pending.json").write_text(json.dumps({"signature": "abc", "action": "x", **extra}))

    return tmp_path, pending


def test_yes_authorizes_for_a_minute(confirm):
    folder, pending = confirm
    pending(at=time.time())
    assert Fake()._confirm("Yes, do it") is False  # the sentence still goes to the LLM
    confirmed = json.loads((folder / "confirmed.json").read_text())
    assert confirmed["signature"] == "abc" and confirmed["until"] > time.time() + 50
    assert not (folder / "pending.json").exists()


def test_anything_else_cancels(confirm):
    folder, pending = confirm
    pending(at=time.time(), consume=True)
    assert Fake()._confirm("No, wait") is True  # resolved by the plugin: not for the LLM
    assert not (folder / "confirmed.json").exists()
    assert not (folder / "pending.json").exists()


def test_old_questions_expire(confirm):
    folder, pending = confirm
    pending(at=time.time() - 300)
    assert Fake()._confirm("Yes") is False
    assert not (folder / "confirmed.json").exists()
