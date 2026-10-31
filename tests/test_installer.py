"""The installer's steps (installer.py): the core's and the plugins', shown as JSON for a window."""

import io
import json
from contextlib import redirect_stdout

import installer
import settings


def test_the_core_and_the_plugins_bring_steps():
    ids = [s.id for s in installer.steps()]
    assert ids[0] == "computer" and ids[-1] == "connect"
    assert {"language", "llm", "models", "service", "pairing", "memory", "eyes"} <= set(ids)
    assert installer.STEPS["memory"].plugin == "memory" and installer.STEPS["memory"].always  # even while off


def test_answers_through_json_lines(monkeypatch):
    out = io.StringIO()
    with redirect_stdout(out):
        failed = installer.main(["--json", "--set", "memory=auto", "--set", "eyes=true", "--set", "pairing=false",
                                 "memory", "eyes", "pairing"])
    events = [json.loads(line) for line in out.getvalue().splitlines()]
    assert failed == 0 and events[-1] == {"event": "finished", "failed": []}
    assert [e["id"] for e in events if e["event"] == "step"] == ["pairing", "memory", "eyes"]
    saved = settings.load()
    assert saved["plugins"] == {"pairing": False, "memory": True, "eyes": True} and saved["memory"] == "auto"


def test_a_wrong_answer_fails_only_its_step():
    out = io.StringIO()
    with redirect_stdout(out):
        failed = installer.main(["--json", "--set", "memory=sometimes", "memory", "eyes"])
    events = [json.loads(line) for line in out.getvalue().splitlines()]
    assert failed == 1 and any(e["event"] == "error" and e["id"] == "memory" for e in events)
    assert any(e["event"] == "done" and e["id"] == "eyes" for e in events)


def test_list_describes_the_questions_for_a_form():
    out = io.StringIO()
    with redirect_stdout(out):
        installer.main(["--list", "--json", "memory"])
    (memory,) = json.loads(out.getvalue())
    assert memory["kind"] == "question" and [c["value"] for c in memory["choices"]] == ["off", "explicit", "auto"]
