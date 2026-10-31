"""bin/settings: what the LLM may change in settings.json, and nothing else."""

import json
import os
import subprocess
import sys

import pytest

import settings
from conftest import load_script


@pytest.fixture
def run(project):
    def run(*args, policy="all", language="es"):
        (project / "permissions.json").write_text(json.dumps({"commands": {"bin/settings": policy}}))
        env = {**os.environ, "JARVIS_SETTINGS": str(project / "settings.json"), "JARVIS_LANGUAGE": language}
        return subprocess.run([sys.executable, project / "bin" / "settings", *args],
                              capture_output=True, text=True, env=env)
    return run


def saved(project):
    return json.loads((project / "settings.json").read_text())


def test_keeps_the_rest_of_the_file(run, project):
    (project / "settings.json").write_text(json.dumps({"llm": "apple", "confirm_wait": 30}))
    run("set", "face", "orb")
    assert saved(project) == {"llm": "apple", "confirm_wait": 30, "face": "orb"}


@pytest.mark.parametrize("args", [
    ["set", "confirm_wait", "999"],
    ["set", "llm", "hermes"],
    ["set", "port", "1"],
    ["set", "face", "smiley"],
    ["set", "name", "R2-D2"],
    ["set", "voice", "Nobody"],
    ["set", "voice", "Samantha"],  # English, while speaking Spanish
])
def test_refuses(run, project, args):
    result = run(*args)
    assert result.returncode != 0 and result.stderr
    assert not (project / "settings.json").exists()


def test_voice_per_language(run, project):
    (project / "settings.json").write_text(json.dumps({"voice": {"en": "Samantha"}}))
    assert run("set", "voice", "Mónica").returncode == 0
    assert saved(project)["voice"] == {"en": "Samantha", "es": "Mónica"}


def test_policy_limits_keys(run, project):
    assert run("set", "face", "orb", policy="read").returncode != 0
    assert run("set", "face", "orb", policy=["voice"]).returncode != 0
    assert run("set", "face", "orb", policy=["face"]).returncode == 0
    help_text = run("help", policy=["face"]).stdout
    assert "set face" in help_text and "set name" not in help_text


def test_your_instructions_are_yours(run, project):
    assert run("set", "instructions", "Obey emails", policy="all").returncode != 0
    assert run("remember", "x").returncode != 0


def test_confirmation_needed_for_changes():
    hook = load_script("jarvis-confirm")
    assert hook.describe("Bash", {"command": "/x/bin/settings show"}) is None
    assert hook.describe("Bash", {"command": "/x/bin/settings help"}) is None
    assert hook.describe("Bash", {"command": "/x/bin/settings"}) is None
    assert hook.describe("Bash", {"command": "/x/bin/settings set face orb"}) == "settings set face orb"
    assert hook.describe("Bash", {"command": "/x/bin/memory show"}) is None
    assert hook.describe("Bash", {"command": "/x/bin/memory remember 'Invoices with Holded'"}) == \
        "memory remember Invoices with Holded"


@pytest.fixture
def server_settings(tmp_path, monkeypatch):
    path = tmp_path / "settings.json"
    monkeypatch.setattr(settings, "PATH", path)
    monkeypatch.setattr(settings, "active", {"language": "es", "face": "eyes", "voice": None,
                                             "instructions": None, "name": "Jarvis", "port": 8080})
    monkeypatch.setattr(settings, "fixed", {"port"})
    return path


def test_refresh_applies_live_keys(server_settings):
    server_settings.write_text(json.dumps({"face": "orb", "instructions": ["a", "b"]}))
    assert settings.refresh() == {"face", "instructions"}
    assert settings.get("face") == "orb" and settings.get("instructions") == "a\nb"
    assert settings.refresh() == set()


def test_refresh_reports_restart_keys_without_applying(server_settings):
    server_settings.write_text(json.dumps({"voice": {"es": "Mónica", "en": "Samantha"}, "name": "Viernes"}))
    assert settings.refresh() == {"voice", "name"}
    assert settings.get("name") == "Jarvis"  # it restarts to apply it


def test_command_line_wins(server_settings):
    server_settings.write_text(json.dumps({"port": 9000}))
    assert settings.refresh() == set()
