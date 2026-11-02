"""Jarvis's own tools over MCP: what they change, what they refuse, and the protocol."""

import json

import pytest

import kernel

import settings

memory = kernel.load("memory")
mcp_server = kernel.load("mcp-server")
import tools
from conftest import here, load_script, mac_only
from plugins.llm_claude.permissions import load


@pytest.fixture
def env(tmp_path, monkeypatch, es):
    global memory
    memory = kernel.load("memory")  # as loaded now (other tests may have loaded the plugins again)
    monkeypatch.setattr(settings, "PATH", tmp_path / "settings.json")
    monkeypatch.setattr(memory, "PATH", tmp_path / "memory.json")
    monkeypatch.setattr(settings, "active", {"name": "Jarvis", "face": "eyes", "memory": "explicit", "port": 8080,
                                                  "plugins": {"memory": True}})
    monkeypatch.setattr(tools, "requested", set())
    return tmp_path


def saved(env):
    return json.loads((env / "settings.json").read_text())


def test_settings_are_saved_for_after_the_answer(env):
    tools.call("set_theme", {"theme": "orb"})
    tools.call("set_name", {"name": "Viernes"})
    tools.call("set_language", {"language": "en"})
    assert saved(env) == {"theme": "orb", "name": "Viernes", "language": "en"}


@mac_only  # the Mac's voices
def test_voice_must_exist_and_speak_the_language(env, monkeypatch):
    monkeypatch.setitem(settings.active, "tts", "avspeech")
    tools.call("set_voice", {"voice": "Mónica"})
    assert saved(env)["voice"] == {"es": "Mónica"}
    with pytest.raises(tools.ToolError):
        tools.call("set_voice", {"voice": "Samantha"})  # English
    with pytest.raises(tools.ToolError):
        tools.call("set_voice", {"voice": "Nobody"})


@pytest.mark.parametrize("name, arguments", [
    ("set_theme", {"theme": "smiley"}), ("set_name", {"name": "R2-D2"}), ("set_language", {"language": "zz"}),
    ("set_theme", {}), ("set_permissions", {"x": 1}), ("forget", {"number": 9}),
])
def test_refusals(env, name, arguments):
    with pytest.raises(tools.ToolError):
        tools.call(name, arguments)


def test_nothing_to_lift_its_safeguards():
    assert not {n for n in tools.TOOLS if any(w in n for w in ("permission", "confirm", "port", "instruction"))}


def test_memory(env):
    tools.call("remember", {"fact": "Has a dog called Toby."})
    assert "1. Has a dog called Toby." in tools.call("get_memory", {})
    tools.call("update", {"number": 1, "fact": "Has a dog called Rex."})
    assert memory.load()["facts"] == ["Has a dog called Rex."]
    with pytest.raises(tools.ToolError):
        tools.call("update", {"number": 5, "fact": "x"})
    tools.call("forget", {"number": 1})
    assert memory.load()["facts"] == []
    settings.active["plugins"] = {"memory": False}  # the plugin off: its tools aren't there
    with pytest.raises(tools.ToolError):
        tools.call("remember", {"fact": "x"})


def test_camera_needs_a_device_with_a_camera(env, monkeypatch):
    with pytest.raises(tools.ToolError):
        tools.call("camera", {"on": True})
    sent = []
    device = type("Session", (), {"frames": 10, "send": lambda self, m: sent.append(m)})()
    monkeypatch.setattr(tools, "session", lambda: device)
    tools.call("camera", {"on": True})
    assert sent == [{"type": "camera", "on": True}]


def test_reload_and_restart_wait_for_the_answer(env):
    tools.call("reload_tools", {})
    tools.call("restart", {})
    assert tools.requested == {"reload", "restart"}


def test_mcp_protocol(env):
    init = mcp_server.handle({"jsonrpc": "2.0", "id": 1, "method": "initialize",
                              "params": {"protocolVersion": "2025-06-18"}})
    assert init["result"]["serverInfo"]["name"] == "anyassistant"
    assert mcp_server.handle({"jsonrpc": "2.0", "method": "notifications/initialized"}) is None
    listed = mcp_server.handle({"jsonrpc": "2.0", "id": 2, "method": "tools/list"})["result"]["tools"]
    assert {t["name"] for t in listed} == set(tools.available())
    called = mcp_server.handle({"jsonrpc": "2.0", "id": 3, "method": "tools/call",
                                "params": {"name": "set_theme", "arguments": {"theme": "smiley"}}})["result"]
    assert called["isError"] and "eyes" in called["content"][0]["text"]
    assert "error" in mcp_server.handle({"jsonrpc": "2.0", "id": 4, "method": "nope"})


def test_claude_gets_the_jarvis_server_only_if_allowed(env, project):
    (project / "permissions.json").write_text(json.dumps({"allowed": {"anyassistant": "all"}}))
    args = load(project, project / ".mcp.json").arguments
    config = json.loads((project / ".build" / "anyassistant-mcp.json").read_text())
    assert config["mcpServers"]["anyassistant"]["url"] == "http://127.0.0.1:8080/mcp"
    assert "mcp__anyassistant" in args
    (project / "permissions.json").write_text(json.dumps({"allowed": {}}))
    assert "mcp__anyassistant" not in load(project, project / ".mcp.json").arguments


def test_the_hook_leaves_jarvis_tools_to_the_server():
    hook = load_script("anyassistant-confirm")
    assert hook.describe("mcp__anyassistant__get_settings", {}) is None
    assert hook.describe("mcp__anyassistant__camera", {"on": True}) is None
    assert hook.describe("mcp__anyassistant__set_name", {"name": "Viernes"}) is None  # the server asks itself


def test_remember_points_to_update():
    assert "use update instead" in tools.TOOLS["remember"].description


def test_switching_llm(env, monkeypatch):
    import llm

    monkeypatch.setattr(llm, "ready", lambda name: None if name != "hermes" else "gateway down")
    first = "apple" if here("llm-apple") else "claude"  # Apple's model only on the Mac
    tools.call("set_llm", {"llm": first})
    assert saved(env) == {"llm": first, "llm_model": None}
    tools.call("set_llm", {"llm": "claude", "model": "opus"})
    assert saved(env)["llm_model"] == "opus"
    for bad in ({"llm": "gpt"}, {"llm": "hermes"}, {"llm": "claude", "model": "rm -rf /"}):
        with pytest.raises(tools.ToolError):
            tools.call("set_llm", bad)
    assert "hermes: not available (gateway down)" in tools.call("get_llms", {})


def test_llm_switch_needs_your_yes():
    assert "set_llm" in tools.NEEDS_YES and "get_llms" not in tools.NEEDS_YES


@pytest.fixture
def asking():
    import paths

    paths.PERMISSIONS.unlink()  # «confirm» on by default


def say_yes():
    """What the plugin «confirmation» writes when the user says «yes»."""
    return kernel.load("confirmation").store.answer(True)


def test_changes_wait_for_your_yes_for_any_llm(env, asking):
    with pytest.raises(tools.ToolError, match="confirmation"):
        tools.call("set_name", {"name": "Viernes"})
    assert not (env / "settings.json").exists()
    assert say_yes()["action"] == 'anyassistant: set_name {"name": "Viernes"}'
    tools.call("set_name", {"name": "Viernes"})
    assert saved(env)["name"] == "Viernes"
    with pytest.raises(tools.ToolError):  # good for one use only
        tools.call("set_name", {"name": "Viernes"})


def test_a_yes_for_one_call_is_not_for_another(env, asking):
    with pytest.raises(tools.ToolError):
        tools.call("set_name", {"name": "Viernes"})
    say_yes()
    with pytest.raises(tools.ToolError):
        tools.call("set_language", {"language": "en"})


def test_what_doesnt_change_anything_doesnt_ask(env, asking):
    tools.call("get_settings", {})
    tools.call("set_theme", {"theme": "orb"})
    tools.call("set_detail", {"level": "concise"})
    tools.call("set_timer", {"seconds": 60})
    assert kernel.load("confirmation").store.pending() is None


def test_showing_or_hiding_parts_of_the_screen(env):
    """«Quita la transcripción»: a setting for every theme, not a new theme."""
    tools.call("set_screen", {"setting": "show_heard", "value": "no"})
    assert saved(env)["show_heard"] is False
    tools.call("set_screen", {"setting": "history", "value": "0"})
    tools.call("set_screen", {"setting": "clock", "value": "24"})
    assert saved(env)["history"] == 0 and saved(env)["clock"] == "24"
    for bad in ({"setting": "show_heard", "value": "maybe"}, {"setting": "theme", "value": "orb"},
                {"setting": "clock", "value": "13"}, {"setting": "history", "value": "many"}):
        with pytest.raises(tools.ToolError):
            tools.call("set_screen", bad)
    assert "set_screen" not in tools.NEEDS_YES  # only the screen: no «yes»
