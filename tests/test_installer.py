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


def test_a_device_step_is_only_named_by_the_setup(monkeypatch):
    """«Your voice» needs this computer's microphone: the window offers it once the server runs; here,
    only named (--json) or how to do it later (the terminal, headless)."""
    voices = installer.kernel.load("voices")
    monkeypatch.setattr(voices, "people", lambda: [])
    monkeypatch.setattr(installer.i18n, "detect", lambda: "en")  # this computer's language may be another
    started = []
    monkeypatch.setattr(installer.STEPS["voice"], "function", lambda session: started.append(session))
    out = io.StringIO()
    with redirect_stdout(out):
        assert installer.main(["--json", "voice"]) == 0
    events = [json.loads(line) for line in out.getvalue().splitlines()]
    (device,) = [e for e in events if e["event"] != "finished"]
    assert device["event"] == "device" and device["id"] == "voice" and device["plugin"] == "voices"
    assert device["action"] == "Register my voice" and "learn my voice" in device["later"]
    out = io.StringIO()
    with redirect_stdout(out):
        assert installer.main(["--defaults", "voice"]) == 0
    assert "– Later, ask for it on a device: «learn my voice»." in out.getvalue()
    assert started == []  # never run by the setup itself


def test_a_device_step_is_left_out_once_done(monkeypatch):
    voices = installer.kernel.load("voices")
    monkeypatch.setattr(voices, "people", lambda: [{"name": "Suvi"}])
    out = io.StringIO()
    with redirect_stdout(out):
        installer.main(["--json", "voice"])
    assert [json.loads(line)["event"] for line in out.getvalue().splitlines()] == ["finished"]


def test_a_device_step_in_spanish(es):
    step = installer.STEPS["voice"].describe()
    assert (step["title"], step["action"]) == ("Tu voz", "Registrar mi voz")
    assert step["help"].startswith("Lee unas frases") and "«aprende mi voz»" in step["later"]
