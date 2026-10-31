"""What Jarvis may use with Claude: the project's MCP servers and commands, only what is allowed.

- .mcp.json: MCP servers, in Claude Code's format (project scope). They are
  authenticated by opening `claude` in the project folder and using /mcp, so they
  belong to the project only, without touching the account's connectors.
- permissions.json:

    {
      "allowed": {"holded": "all", "other": ["get_x", "list_y"], "jarvis": "all"},
      "commands": {"bin/gog": "all"},
      "confirm": true
    }

  "allowed": tools of each .mcp.json server ("all" or a list; it sees the server's
  other tools, but they are denied). A server that isn't listed is denied entirely.
  «jarvis» is its own MCP server (server/tools.py: face, voice, memory, camera…).
  "commands": programs (paths relative to the project) it may run, and nothing
  else: it gets Claude Code's terminal limited to them, plus the output of
  `<command> help` in the prompt so it knows how to use them. Each value is the
  command's policy, read by the command itself (bin/gog: "read", "all" or a list).
  "confirm" (on by default): actions that write need the user's «yes», through
  the bin/jarvis-confirm hook.

Claude starts only with the .mcp.json servers (--strict-mcp-config: no claude.ai
connectors, no plugins) and without its own tools (Bash, Edit…) other than that
limited terminal and, with «eyes» in the settings, Read for the camera's image only.
"""

import json
import logging
import re
import shlex
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path

import kernel
import paths
import settings

log = logging.getLogger("llm")


@dataclass
class Permissions:
    arguments: list[str] = field(default_factory=list)  # for `claude`
    instructions: str = ""  # for the system prompt
    tools: bool = False  # whether it may use any (MCP or command)


def prefix(server: str) -> str:
    """«claude.ai Google Drive» → «mcp__claude_ai_Google_Drive», as Claude Code names it."""
    return "mcp__" + re.sub(r"[^A-Za-z0-9_-]", "_", server)


def command_help(command: Path) -> str:
    try:
        output = subprocess.run([str(command), "help"], capture_output=True, text=True, timeout=30).stdout
    except OSError as e:
        log.warning("cannot run %s: %s", command, e)
        return ""
    return output.strip()


def load(root: Path | None = None, servers: Path | None = None) -> Permissions:
    """What Claude may use, from your permissions.json and .mcp.json (paths.py's places;
    root: one folder with everything, for tests)."""
    home, app = root or paths.HOME, root or paths.APP
    cache = root / ".build" if root else paths.CACHE
    servers = servers or paths.MCP
    path = home / "permissions.json"
    config = json.loads(path.read_text()) if path.exists() else {}
    allowed = config.get("allowed", {})
    commands = [app / c for c in config.get("commands", [])]  # list or {path: policy}

    args = ["--strict-mcp-config", "--setting-sources", ""]
    allow, deny = [], []

    configs, names = [], {}
    if servers.exists():
        configs.append(str(servers))
        names.update(json.loads(servers.read_text()).get("mcpServers", {}))
    if "jarvis" in allowed:  # its own tools (server/tools.py), served by the server itself
        own = {"type": "http", "url": f"http://127.0.0.1:{settings.get('port', 8080)}/mcp"}
        path = cache / "jarvis-mcp.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps({"mcpServers": {"jarvis": own}}))
        configs.append(str(path))
        names["jarvis"] = own
    if configs and allowed:
        args += ["--mcp-config", *configs]
        for server in names:
            tools = allowed.get(server)
            if tools is None:
                deny.append(prefix(server))
            elif tools == "all":
                allow.append(prefix(server))
            else:
                allow += [f"{prefix(server)}__{t}" for t in tools]
        for server in allowed.keys() - names.keys():
            log.warning("permissions.json allows «%s», which isn't in .mcp.json", server)

    instructions = ""
    tools = []  # Claude Code's own tools, each limited by `allow`
    eyes = kernel.module("eyes")
    if eyes:  # the camera's image, and no other file
        tools.append("Read")
        allow.append(f"Read(/{eyes.FRAME})")
    if commands:
        tools.append("Bash")
        texts = []
        for command in commands:
            if not command.exists():
                log.warning("permissions.json allows %s, which doesn't exist", command)
                continue
            allow.append(f"Bash({command}:*)")
            relative = str(command.relative_to(app))
            # The relative path («bin/gog») becomes the full one, unless it already is.
            texts.append(re.sub(rf"(?<![\w/]){re.escape(relative)}", str(command), command_help(command)))
        instructions = (
            "\nIn the terminal you may run only these commands, with their full path, "
            "one at a time and without pipes or redirections:\n\n" + "\n\n".join(texts)
        )
    args += ["--tools", ",".join(tools)]

    if allow and config.get("confirm", True) and kernel.enabled("confirmation"):
        hooks = cache / "claude-settings.json"
        hooks.parent.mkdir(parents=True, exist_ok=True)
        # With Jarvis's own Python, not whatever python3 the system has.
        hook = f"{shlex.quote(sys.executable)} {shlex.quote(str(app / 'bin' / 'jarvis-confirm'))}"
        hooks.write_text(json.dumps({"hooks": {"PreToolUse": [{
            "matcher": "Bash|mcp__.*",
            "hooks": [{"type": "command", "command": hook}],
        }]}}))
        args += ["--settings", str(hooks)]
        log.info("actions that write ask for confirmation")
    if allow:
        args += ["--allowedTools", *allow]
    if deny:
        args += ["--disallowedTools", *deny]
    log.info("allowed: %s", ", ".join(allow) or "nothing")
    return Permissions(args, instructions, bool(allow))
