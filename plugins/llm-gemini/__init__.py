"""Gemini through Google's Gemini CLI, with your Google account (signed in with `gemini`), through its
ACP mode (`gemini --acp`; server/llm/acp.py does the talking).

One process per device's LLM, a session per conversation, the answer in pieces, the camera's image
with the question. Its model: «llm_model», or Gemini CLI's own choice. Jarvis's instructions replace
its system prompt (GEMINI_SYSTEM_MD, a file of its own).

What it may use, by a policy of Jarvis's at the administrator's level (--admin-policy: above yours):
- Its MCP servers (yours, in ~/.gemini/settings.json; untouched) and, if permissions.json allows
  «anyassistant», Jarvis's (at /mcp?device=…; a list there allows only those tools).
- Before an MCP tool it asks (policy «ask_user») and Jarvis answers: reads (get_, list_…) and
  Jarvis's own tools go through; anything else waits while Jarvis asks you aloud, and your «yes»
  allows that call, once. Tools their server marks as read-only (readOnlyHint) run without asking.
- Its web search (it only reads the web), and nothing else: its file, terminal, web fetch and memory
  tools are denied (not even shown to it), so permissions.json's «commands» don't apply to it. An
  empty folder is its workspace.

Google stopped accepting Gemini CLI with some free accounts («Gemini Code Assist for individuals»:
«migrate to Antigravity»): then it says so (it can't be fixed here).
"""

import asyncio
import json
import logging
import os
import re
import shutil
from pathlib import Path

import paths
from llm import register
from llm.acp import ACP, own_tools, spoken

log = logging.getLogger("llm")
TITLE = re.compile(r"^(?P<tool>.+) \((?P<server>.+) MCP Server\)$")  # how it titles an MCP tool call
POLICY = """# Jarvis's rules for Gemini CLI (the administrator's level: above your own policies).
[[rule]]
toolName = "*"
decision = "deny"
priority = 100
denyMessage = "Not available here: only the MCP tools and web search."

[[rule]]
toolName = "google_web_search"
decision = "allow"
priority = 200

[[rule]]
toolName = "*"
mcpName = "*"
decision = "ask_user"
priority = 300

[[rule]]
toolName = "*"
mcpName = "*"
toolAnnotations = { readOnlyHint = true }
decision = "allow"
priority = 310
"""


def signed_in() -> bool:
    if any(os.environ.get(k) for k in ("GEMINI_API_KEY", "GOOGLE_API_KEY", "GOOGLE_GENAI_USE_VERTEXAI")):
        return True
    return (Path.home() / ".gemini" / "oauth_creds.json").exists()


@register("gemini")
class Gemini(ACP):
    spoken = ["gemini", "géminis", "geminis", "yemini", "jemini", "yeminai", "gemenis"]
    NAME, LOGIN = "Gemini", "gemini"
    SENTENCES = {"ineligible": "speech.gemini_ineligible", "unsafe": "speech.gemini_unsafe"}
    folder = paths.CACHE / "gemini-empty"

    @classmethod
    def ready(cls):
        if not shutil.which("gemini"):
            return "Gemini CLI isn't installed"
        return None if signed_in() else "Gemini CLI isn't signed in: run gemini and sign in with Google"

    def policy(self) -> str:
        own = own_tools(getattr(self, "device", None))
        text = POLICY
        if own and own[1] is None:
            text += '\n[[rule]]\ntoolName = "*"\nmcpName = "anyassistant"\ndecision = "allow"\npriority = 400\n'
        elif own:  # only those
            text += '\n[[rule]]\ntoolName = "*"\nmcpName = "anyassistant"\ndecision = "deny"\npriority = 400\n'
            text += (f'\n[[rule]]\nmcpName = "anyassistant"\ntoolName = {json.dumps(own[1])}\n'
                     'decision = "allow"\npriority = 410\n')
        return text

    def command(self):
        path = self.folder / "policy.toml"
        path.write_text(self.policy())
        command = [shutil.which("gemini") or "gemini", "--acp", "--admin-policy", str(path)]
        return command + (["--model", self.model] if self.model else [])

    def environment(self):
        return {"GEMINI_SYSTEM_MD": str(self.folder / "system.md"), "GEMINI_CLI_TRUST_WORKSPACE": "true"}

    def before_session(self):
        (self.folder / "system.md").write_text(self.text())  # read for each new session

    def servers(self):
        own = own_tools(getattr(self, "device", None))
        return [{"type": "http", "name": "anyassistant", "url": own[0], "headers": []}] if own else []

    async def _start(self):
        self.before_session()  # it needs the file from the start
        self._unsafe = False
        await super()._start()
        await asyncio.sleep(0.2)  # its stderr, read apart, says it before initialize's answer
        if self._unsafe:  # it would run without Jarvis's rules: not at all
            await self._stop()
            raise RuntimeError("unsafe: Gemini CLI didn't load Jarvis's policy")

    def stderr(self, line):
        if "Policy file error" in line:  # it ignores the whole file then
            log.error("Gemini CLI: %s", line)
            self._unsafe = True

    def tool(self, call):
        """Its policy asks only about MCP tools («other», titled «tool (server MCP Server)», with their
        arguments as text); one of its own (read, edit, execute…), refused all the same; an MCP title
        it doesn't recognise still asks."""
        if (call.get("kind") or "other") != "other":
            return None
        title = call.get("title") or ""
        arguments = {}
        for part in call.get("content") or []:
            try:
                found = json.loads(((part or {}).get("content") or {}).get("text") or "")
                arguments = found if isinstance(found, dict) else arguments
            except ValueError:
                pass
        match = TITLE.match(title)
        if not match:
            return "", title, arguments, spoken(title, arguments)
        server, tool = match["server"], match["tool"]
        return server, tool, arguments, f"{server}: {spoken(tool, arguments)}"

    def trouble(self, message):
        text = message.lower()
        if text.startswith("unsafe"):
            return "unsafe"
        if "no longer supported" in text or "ineligible" in text or "antigravity" in text:
            return "ineligible"
        if "quota" in text or "resource_exhausted" in text or "rate limit" in text or "429" in text:
            return "limit"
        if "auth" in text or "login" in text or "credentials" in text:
            return "signed_out"
        if "enotfound" in text or "fetch failed" in text or "network" in text or "econnrefused" in text:
            return "offline"
        return "failed"
