"""Claude through the Claude Code CLI: uses your session and subscription, no API key.

A conversation is a `claude -p` process in stream-json mode: it receives messages
on stdin and returns the answer in pieces (--include-partial-messages). Without
Claude Code's own tools or CLAUDE.md. MCP servers and commands: only the
project's ones that permissions.json allows (see llm/permissions.py); without
it, none. Requires `claude` installed and signed in.
"""

import asyncio
import json
import logging
from pathlib import Path

import i18n
from llm import LLM, instructions, permissions, register

log = logging.getLogger("llm")

CLAUDE_INSTRUCTIONS = """
Each message starts with <now>…</now>, the current date and time: use them only
when asked about them and don't mention them otherwise."""

TOOL_INSTRUCTIONS = """
You have tools to look up the user's services: use them when needed and sum up
the result in one or two sentences to be said out loud.
For actions that change data, don't ask for confirmation yourself: the system
asks on its own. Only ask if it isn't clear what to do (which emails, which
day…); if it is clear, call the tool directly.
If a tool says it isn't authorized or that a sign-in is needed, explain how to
fix it in Jarvis's project (not on claude.ai): Holded and other MCP servers, with
«claude» in the project folder and /mcp; Google, with bin/gog-authorize. After
that, telling you to reload the tools is enough."""

ROOT = Path(__file__).resolve().parents[2]
# An empty folder as cwd: that way it loads no project's CLAUDE.md.
EMPTY = ROOT / ".build" / "claude-empty"
MCP_JSON = ROOT / ".mcp.json"


@register("claude")
class Claude(LLM):
    def __init__(self, model=None, mcp=None):
        super().__init__(model or "sonnet", mcp or str(MCP_JSON))
        EMPTY.mkdir(parents=True, exist_ok=True)
        self._load_permissions()
        self._process = None
        self._turn = asyncio.Lock()

    async def _start(self):
        self._process = await asyncio.create_subprocess_exec(
            "claude", "-p",
            "--input-format", "stream-json",
            "--output-format", "stream-json",
            "--include-partial-messages", "--verbose",
            "--model", self.model,
            "--system-prompt", self._instructions,
            "--no-session-persistence",
            *self._permissions.arguments,
            cwd=EMPTY,
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            limit=1 << 20,  # some stream-json lines exceed the default 64 KB
        )
        asyncio.ensure_future(self._errors(self._process))

    async def _errors(self, process):
        async for line in process.stderr:
            log.warning("claude: %s", line.decode().rstrip())

    async def _stop(self):
        if self._process and self._process.returncode is None:
            self._process.stdin.close()
            try:
                await asyncio.wait_for(self._process.wait(), 2)
            except asyncio.TimeoutError:
                self._process.kill()
        self._process = None

    async def close(self):
        await self._stop()

    def _load_permissions(self):
        """Reads .mcp.json and permissions.json: on every conversation, to pick up changes."""
        self._permissions = permissions.load(ROOT, Path(self.mcp))
        self._instructions = instructions() + CLAUDE_INSTRUCTIONS
        if self._permissions.tools:
            self._instructions += TOOL_INSTRUCTIONS + self._permissions.instructions

    async def new(self):
        async with self._turn:
            await self._stop()
            self._load_permissions()
            await self._start()

    async def answer(self, text: str):
        async with self._turn:
            if not self._process or self._process.returncode is not None:
                await self._start()
            message = {
                "type": "user",
                "message": {"role": "user", "content": f"<now>{i18n.L.now_spoken()}</now>\n{text}"},
            }
            self._process.stdin.write(json.dumps(message).encode() + b"\n")
            await self._process.stdin.drain()
            said = False
            while True:
                line = await self._process.stdout.readline()
                if not line:  # the process died: the next message starts another
                    yield i18n.L("speech.connection_cut")
                    return
                event = json.loads(line)
                if event.get("type") == "stream_event":
                    delta = event["event"].get("delta", {})
                    block = event["event"].get("content_block", {})
                    if delta.get("type") == "text_delta":
                        said = True
                        yield delta["text"]
                    elif block.get("type") == "text" and said:
                        # New text after a tool: without the space it stuck to the
                        # previous one («…contactos.Tienes 72…»).
                        yield " "
                    elif block.get("type") == "tool_use":
                        log.info("tool: %s", block.get("name"))
                        if not said:
                            # So there is no silence while the tool runs (asking for it
                            # in the prompt isn't enough: it almost never does it).
                            said = True
                            yield i18n.L("speech.wait") + " "
                elif event.get("type") == "result":
                    if event.get("is_error"):
                        error = str(event.get("result", ""))
                        log.warning("Claude error: %s", error)
                        if "login" in error.lower():
                            # Signed out: this process stays useless even after signing
                            # in again; the next message starts another.
                            self._process.kill()
                            yield i18n.L("speech.no_login")
                        else:
                            yield i18n.L("speech.llm_failed")
                    return
