"""Jarvis's own tools over MCP: what they change, what they refuse, and the protocol."""

import json

import pytest

import memory
import mcp_server
import settings
import tools
from conftest import load_script
from llm.permissions import load


@pytest.fixture
def env(tmp_path, monkeypatch, es):
    monkeypatch.setattr(settings, "PATH", tmp_path / "settings.json")
    monkeypatch.setattr(memory, "PATH", tmp_path / "memory.json")
    monkeypatch.setattr(settings, "active", {"name": "Jarvis", "face": "eyes", "memory": "explicit", "port": 8080})
    monkeypatch.setattr(tools, "requested", set())
    return tmp_path


def saved(env):
    return json.loads((env / "settings.json").read_text())


def test_settings_are_saved_for_after_the_answer(env):
    tools.call("set_face", {"face": "orb"})
    tools.call("set_name", {"name": "Viernes"})
    tools.call("set_language", {"language": "en"})
    assert saved(env) == {"face": "orb", "name": "Viernes", "language": "en"}


def test_voice_must_exist_and_speak_the_language(env):
    tools.call("set_voice", {"voice": "Mónica"})
    assert saved(env)["voice"] == {"es": "Mónica"}
    with pytest.raises(tools.ToolError):
        tools.call("set_voice", {"voice": "Samantha"})  # English
    with pytest.raises(tools.ToolError):
        tools.call("set_voice", {"voice": "Nobody"})


@pytest.mark.parametrize("name, arguments", [
    ("set_face", {"face": "smiley"}), ("set_name", {"name": "R2-D2"}), ("set_language", {"language": "zz"}),
    ("set_face", {}), ("set_permissions", {"x": 1}), ("forget", {"number": 9}),
])
def test_refusals(env, name, arguments):
    with pytest.raises(tools.ToolError):
        tools.call(name, arguments)


def test_nothing_to_lift_its_safeguards():
    assert not {n for n in tools.TOOLS if any(w in n for w in ("permission", "confirm", "llm", "port", "instruction"))}


def test_memory(env):
    tools.call("remember", {"fact": "Has a dog called Toby."})
    assert "1. Has a dog called Toby." in tools.call("get_memory", {})
    tools.call("update", {"number": 1, "fact": "Has a dog called Rex."})
    assert memory.load()["facts"] == ["Has a dog called Rex."]
    with pytest.raises(tools.ToolError):
        tools.call("update", {"number": 5, "fact": "x"})
    tools.call("forget", {"number": 1})
    assert memory.load()["facts"] == []
    settings.active["memory"] = "off"
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
    assert init["result"]["serverInfo"]["name"] == "jarvis"
    assert mcp_server.handle({"jsonrpc": "2.0", "method": "notifications/initialized"}) is None
    listed = mcp_server.handle({"jsonrpc": "2.0", "id": 2, "method": "tools/list"})["result"]["tools"]
    assert {t["name"] for t in listed} == set(tools.TOOLS)
    called = mcp_server.handle({"jsonrpc": "2.0", "id": 3, "method": "tools/call",
                                "params": {"name": "set_face", "arguments": {"face": "smiley"}}})["result"]
    assert called["isError"] and "eyes or orb" in called["content"][0]["text"]
    assert "error" in mcp_server.handle({"jsonrpc": "2.0", "id": 4, "method": "nope"})


def test_claude_gets_the_jarvis_server_only_if_allowed(env, project):
    (project / "permissions.json").write_text(json.dumps({"allowed": {"jarvis": "all"}}))
    args = load(project, project / ".mcp.json").arguments
    config = json.loads((project / ".build" / "jarvis-mcp.json").read_text())
    assert config["mcpServers"]["jarvis"]["url"] == "http://127.0.0.1:8080/mcp"
    assert "mcp__jarvis" in args
    (project / "permissions.json").write_text(json.dumps({"allowed": {}}))
    assert "mcp__jarvis" not in load(project, project / ".mcp.json").arguments


def test_confirmation_for_changes_but_not_for_the_camera():
    hook = load_script("jarvis-confirm")
    assert hook.describe("mcp__jarvis__get_settings", {}) is None
    assert hook.describe("mcp__jarvis__camera", {"on": True}) is None
    assert hook.describe("mcp__jarvis__set_face", {"face": "orb"}) == 'jarvis: set_face {"face": "orb"}'
    assert hook.describe("mcp__jarvis__remember", {"fact": "x"})
    assert hook.describe("mcp__jarvis__update", {"number": 1, "fact": "x"})


def test_remember_points_to_update():
    assert "use update instead" in tools.TOOLS["remember"][1]
