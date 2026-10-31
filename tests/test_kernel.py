"""The core: plugins found, loaded, on and off; yours replace the system's."""

import json

import pytest

import kernel
import paths
import settings
import tools


@pytest.fixture
def yours(tmp_path, monkeypatch):
    """A plugins folder of your own, and the kernel finding again."""
    monkeypatch.setattr(paths, "USER_PLUGINS", tmp_path / "plugins")
    monkeypatch.setattr(settings, "active", {})
    kernel.reset()
    yield tmp_path / "plugins"
    kernel.reset()


def make(folder, plugin_id, code, **manifest):
    plugin = folder / plugin_id
    plugin.mkdir(parents=True)
    (plugin / "plugin.json").write_text(json.dumps({"name": plugin_id, "kind": "skill", **manifest}))
    (plugin / "__init__.py").write_text(code)
    return plugin


GREETER = '''
from skills import Skill, skill

@skill
class Greeter(Skill):
    order = 1
    def answer(self, text, toks):
        return "{reply}" if "hola" in text.lower() else None
'''


def test_every_system_plugin_is_found_and_on():
    found = kernel.discover()
    assert {"llm-claude", "stt-parakeet", "skill-alarms", "vad-silero", "plugin-manager"} <= set(found)
    off = {p for p in found if not kernel.enabled(p)}
    assert off == {"pairing"}  # everything comes on, but pairing (it was opt-in before plugins too)


def test_your_plugin_works_and_can_be_turned_off(yours):
    import skills

    make(yours, "skill-greeter", GREETER.format(reply="¡Hola!"))
    kernel.load("skill-greeter")
    assert skills.quick("Hola, Jarvis") == "¡Hola!"
    settings.active["plugins"] = {"skill-greeter": False}  # live: no restart
    assert skills.quick("Hola, Jarvis") is None


def test_yours_replaces_the_systems(yours):
    make(yours, "skill-clock", GREETER.format(reply="Mi reloj"), description="mine")
    assert kernel.plugin("skill-clock").yours
    assert kernel.plugin("skill-clock").manifest["description"] == "mine"


def test_off_takes_what_needs_it_off(yours):
    settings.active["plugins"] = {"skill-alarms": False}
    assert not kernel.enabled("skill-ringing")  # it requires skill-alarms


def test_turning_off_tools_and_engines(yours):
    settings.active["plugins"] = {"skill-alarms": False, "llm-hermes": False}
    assert "set_timer" not in tools.available()
    import llm

    assert "hermes" not in llm.available()


def test_a_plugins_texts_join_jarviss(yours):
    import i18n

    plugin = make(yours, "skill-greeter", "")
    (plugin / "locales").mkdir()
    (plugin / "locales" / "es.json").write_text(json.dumps({"speech": {"greeting": "¡Buenas!"}}))
    assert i18n.Locale("es")("speech.greeting") == "¡Buenas!"


def test_a_broken_plugin_doesnt_stop_the_rest(yours):
    make(yours, "skill-broken", "raise RuntimeError('oops')")
    kernel.load_all()
    assert kernel.plugin("skill-clock").module is not None


def test_by_voice_but_never_the_safeguards(yours, tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "PATH", tmp_path / "settings.json")
    assert "skill-alarms" in tools.call("list_plugins", {})
    assert tools.call("disable_plugin", {"plugin_id": "skill-arithmetic"}).startswith("Off.")
    assert settings.load()["plugins"] == {"skill-arithmetic": False}
    assert "these need it" in tools.call("disable_plugin", {"plugin_id": "skill-alarms"}).lower()
    for refused in ("plugin-manager", "nope"):
        with pytest.raises(tools.ToolError):
            tools.call("disable_plugin", {"plugin_id": refused})
    settings.active["llm"] = "claude"
    with pytest.raises(tools.ToolError, match="in use"):
        tools.call("disable_plugin", {"plugin_id": "llm-claude"})
    assert "disable_plugin" in tools.NEEDS_YES and "enable_plugin" not in tools.NEEDS_YES


def test_no_plugin_breaks_whatever_is_imported_first():
    """main.py imports llm before tools: loading every plugin then broke Claude's and Hermes's."""
    import subprocess
    import sys

    from conftest import ROOT

    code = "import llm, tools; tools.available(); print(llm.available())"
    result = subprocess.run([sys.executable, "-c", code], cwd=ROOT / "server", capture_output=True, text=True)
    assert "couldn't load" not in result.stderr, result.stderr
    assert "claude" in result.stdout and "hermes" in result.stdout


def test_pyproject_lists_each_plugins_packages():
    """plugin.json «needs» is the source; pyproject's extras (for uv) must say the same."""
    import tomllib

    from conftest import ROOT

    extras = tomllib.loads((ROOT / "pyproject.toml").read_text())["project"]["optional-dependencies"]
    declared = {p.id: p.needs["python"] for p in kernel.discover().values() if p.needs.get("python")
                and not p.yours}
    assert extras == declared


def test_a_plugin_that_doesnt_fit_is_off(tmp_path, monkeypatch):
    import paths

    mine = tmp_path / "plugins"
    (mine / "needs-much").mkdir(parents=True)
    (mine / "needs-much" / "plugin.json").write_text(json.dumps(
        {"name": "x", "kind": "feature", "needs": {"python": ["surely-not-installed-pkg>=1"], "system": ["plan9"]}}))
    (mine / "needs-much" / "__init__.py").write_text("")
    monkeypatch.setattr(paths, "USER_PLUGINS", mine)
    kernel.reset()
    assert not kernel.enabled("needs-much") and kernel.wanted("needs-much")
    assert any("plan9" in w for w in kernel.unfit("needs-much"))
    assert "surely-not-installed-pkg>=1" not in kernel.requirements()  # another system: not even installed
    kernel.reset()
