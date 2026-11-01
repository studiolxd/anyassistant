"""OpenCode, with whatever providers you connected in it (`opencode auth login`: OpenCode Go or Zen,
your own…), through its ACP mode (`opencode acp`; server/llm/acp.py does the talking).

One process per device's LLM, a session per conversation, the answer in pieces, the camera's image
with the question (if its model sees). Its model: «llm_model» (provider/model, as `opencode models`
lists them), or the one you chose in OpenCode. Jarvis's instructions go with the first message of
each conversation: its own system prompt stays (its free models only answer OpenCode's own requests).

Its configuration for this run comes on top of yours (OPENCODE_CONFIG_CONTENT; your files untouched):
- Its MCP servers, yours and, if permissions.json allows «anyassistant», Jarvis's (at /mcp?device=…).
- Its permissions: every tool asks («ask»), and Jarvis answers. Its own tools (files, terminal, web
  fetch, subagents…) are refused, so permissions.json's «commands» don't apply to it; its web search
  is allowed (it only reads the web). MCP tools that read (get_, list_… of the servers it knows) and
  Jarvis's own are allowed by OpenCode itself. Anything else waits while Jarvis asks you aloud: your
  «yes» allows that call, once. (OpenCode calls MCP tools from code it writes, «execute», and its
  request doesn't say which tool: the question names what the code calls.)
Its tools stay in the list, refused, rather than removed: removing them, its free models refuse
to answer. An empty folder is its workspace.
"""

import json
import re
import shutil
from pathlib import Path

import kernel
import paths
from llm import register
from llm.acp import ACP, own_tools, spoken

# OpenCode's own tools (what its permission requests are about, by kind or title): refused.
OWN_KINDS = {"read", "edit", "delete", "move", "search", "execute", "fetch", "think", "switch_mode"}
OWN = {"read", "edit", "write", "glob", "grep", "shell", "bash", "skill", "subagent", "task", "webfetch",
       "question", "external_directory", "todowrite", "apply_patch", "lsp", "list", "patch"}
CALL = re.compile(r"tools\.([A-Za-z0-9_-]+)\.([A-Za-z0-9_-]+)\s*\(")  # a tool called from its code
CONFIG = Path.home() / ".config" / "opencode"


def name(server: str) -> str:
    """A server's name as OpenCode names its tools (server_tool)."""
    return re.sub(r"[^a-zA-Z0-9_-]", "_", server)


def reads() -> tuple[str, ...]:
    confirmation = kernel.module("confirmation")
    return confirmation.store.READS if confirmation else ()


def your_servers() -> list[str]:
    """The MCP servers in your OpenCode configuration (only their names)."""
    found = []
    for file in (CONFIG / "opencode.json", CONFIG / "opencode.jsonc"):
        try:
            text = file.read_text()
        except OSError:
            continue
        text = re.sub(r'^\s*//.*$|(?<!:)//[^"\n]*$', "", text, flags=re.M)  # JSONC's comments
        try:
            found += list((json.loads(text).get("mcp") or {}).keys())
        except (ValueError, AttributeError):
            pass
    return found


@register("opencode")
class OpenCode(ACP):
    spoken = ["opencode", "open code", "openco", "oven code", "opencod", "open cod"]
    NAME, LOGIN = "OpenCode", "opencode auth login"
    SENTENCES = {"provider": "speech.opencode_provider"}
    folder = paths.CACHE / "opencode-empty"

    @classmethod
    def ready(cls):
        return None if shutil.which("opencode") else "OpenCode isn't installed"

    def command(self):
        return [shutil.which("opencode") or "opencode", "acp"]

    def config(self) -> dict:
        own = own_tools(getattr(self, "device", None))
        rules = {"*": "ask", "websearch": "allow"}
        # Its own ways to read what MCP servers expose (named like that from its code).
        rules.update({f"{prefix}{tool}": "allow" for prefix in ("", "opencode_")
                      for tool in ("list_mcp_resources", "read_mcp_resource")})
        for server in your_servers():
            rules.update({f"{name(server)}_{prefix}*": "allow" for prefix in reads()})
        config = {"permission": rules}
        if own:
            url, only = own
            config["mcp"] = {"anyassistant": {"type": "remote", "url": url}}
            if only is None:
                rules["anyassistant_*"] = "allow"
            else:
                rules["anyassistant_*"] = "deny"
                rules.update({f"anyassistant_{tool}": "allow" for tool in only})
        if self.model:
            config["model"] = self.model
        return config

    def environment(self):
        return {"OPENCODE_CONFIG_CONTENT": json.dumps(self.config()), "OPENCODE_DISABLE_PROJECT_CONFIG": "1",
                "OPENCODE_DISABLE_AUTOUPDATE": "1"}

    def preamble(self):
        return self.text()

    def tool(self, call):
        title, kind = call.get("title") or "", call.get("kind") or ""
        arguments = call.get("rawInput") or {}
        if title == "execute" and isinstance(arguments.get("code"), str):  # its code calls MCP tools
            calls = [(s, t) for s, t in CALL.findall(arguments["code"]) if s != "opencode"]
            asked = [(s, t) for s, t in calls if s != "anyassistant" and not t.startswith(reads())]
            if len(asked) == 1:  # the one OpenCode asks about (reads and Jarvis's need nobody)
                server, tool = asked[0]
                return server, tool, {"code": arguments["code"]}, f"{server}: {spoken(tool, {})}"
            # Which one, unknown (several, or not named plainly): it asks, saying the code itself.
            code = " ".join(arguments["code"].split())
            return "", "execute", {"code": arguments["code"]}, code if len(code) <= 160 else code[:160] + "…"
        if kind in OWN_KINDS or title in OWN:
            return None
        for server in ["anyassistant", *your_servers()]:  # a tool not called from code: server_tool
            if title.startswith(name(server) + "_"):
                tool = title[len(name(server)) + 1:]
                return server, tool, arguments, f"{server}: {spoken(tool, arguments)}"
        return "", title, arguments, spoken(title, arguments)  # unknown: it asks

    def trouble(self, message):
        text = message.lower()
        if "authentication required" in text or "provider authentication" in text:
            return "provider"
        if "usage limit" in text or "quota" in text or "subscription is required" in text or "rate limit" in text:
            return "limit"
        if "unable to connect" in text or "fetch failed" in text or "enotfound" in text or "network" in text:
            return "offline"
        return "failed"
