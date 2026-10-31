"""What Claude may use: only the allowed MCP servers, tools and commands."""

import json

from plugins.llm_claude.permissions import load, prefix


def setup(root, permissions, servers=("holded", "other")):
    (root / "permissions.json").write_text(json.dumps(permissions))
    mcp = root / ".mcp.json"
    mcp.write_text(json.dumps({"mcpServers": {s: {"type": "http", "url": "https://x"} for s in servers}}))
    return mcp


def values(args, flag):
    """The values after a flag, up to the next flag."""
    if flag not in args:
        return []
    rest = args[args.index(flag) + 1:]
    return rest[: next((i for i, a in enumerate(rest) if a.startswith("--")), len(rest))]


def test_prefix_like_claude_code():
    assert prefix("claude.ai Google Drive") == "mcp__claude_ai_Google_Drive"


def test_nothing_allowed(project):
    p = load(project, project / ".mcp.json")
    assert not p.tools
    assert "--strict-mcp-config" in p.arguments
    assert values(p.arguments, "--tools") == [""]
    assert "--allowedTools" not in p.arguments


def test_servers_all_some_or_none(project):
    mcp = setup(project, {"allowed": {"holded": "all"}})
    p = load(project, mcp)
    assert values(p.arguments, "--allowedTools") == ["mcp__holded"]
    assert values(p.arguments, "--disallowedTools") == ["mcp__other"]

    setup(project, {"allowed": {"other": ["get_x", "list_y"]}})
    p = load(project, mcp)
    assert values(p.arguments, "--allowedTools") == ["mcp__other__get_x", "mcp__other__list_y"]
    assert values(p.arguments, "--disallowedTools") == ["mcp__holded"]


def test_commands_get_a_limited_terminal_and_their_help(project):
    tool = project / "bin" / "tool"
    tool.write_text("#!/bin/sh\necho 'bin/tool does things'\n")
    tool.chmod(0o755)
    setup(project, {"commands": {"bin/tool": "all"}})
    p = load(project, project / ".mcp.json")
    assert values(p.arguments, "--tools") == ["Bash"]
    assert values(p.arguments, "--allowedTools") == [f"Bash({tool}:*)"]
    assert f"{tool} does things" in p.instructions  # with the full path


def test_missing_command_is_not_allowed(project):
    setup(project, {"commands": ["bin/missing"]})
    p = load(project, project / ".mcp.json")
    assert not p.tools


def test_confirmation_hook_on_by_default(project):
    mcp = setup(project, {"allowed": {"holded": "all"}})
    p = load(project, mcp)
    settings = json.loads((project / ".build" / "claude-settings.json").read_text())
    hook = settings["hooks"]["PreToolUse"][0]
    assert hook["hooks"][0]["command"].endswith("bin/anyassistant-confirm")
    assert "--settings" in p.arguments

    setup(project, {"allowed": {"holded": "all"}, "confirm": False})
    assert "--settings" not in load(project, mcp).arguments
