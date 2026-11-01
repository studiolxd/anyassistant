"""Codex through OpenAI's Codex CLI: your ChatGPT subscription (`codex login`), no API key.

A conversation is a thread of `codex app-server` (the JSON-RPC protocol over stdin/stdout that
its IDE extensions use): one process per device's LLM, kept between conversations, a new thread
for each (new()); the answer comes in pieces (item/agentMessage/delta), so the voice starts
before it ends. The camera's image goes with the question that looked.

What it may use:
- Its own MCP servers, as you configured them in Codex (~/.codex/config.toml; untouched) and, if
  permissions.json allows «anyassistant», Jarvis's own tools (server/tools.py, at
  /mcp?device=…, so they act on this conversation's device; a list there enables only those).
- Your «yes» before what changes something: Codex asks its client before each MCP tool (approval
  policy on-request) and Jarvis answers with the plugin «confirmation» (let_through, the same
  rule as Claude's hook): reads (get_, list_, search_…) and Jarvis's own tools (they ask for
  your «yes» themselves) go through; anything else is refused until you say «yes» to exactly
  that call, and then Codex calls it again. Tools their server marks as read-only
  (readOnlyHint), Codex runs without asking.
- Nothing else: Codex's terminal, file tools, image viewer, browser, computer use, plugins, apps
  and subagents are turned off, and it runs in a read-only sandbox with an empty folder as its
  workspace. So permissions.json's «commands» (bin/gog) don't apply to it, and it can't open the
  camera's image by itself (its image viewer would open any picture): it sees it when the
  question comes with one. Its web search stays (it only reads the web).
Requires `codex` installed and signed in (`codex login`, with ChatGPT).
"""

import asyncio
import base64
import itertools
import json
import logging
import os
import shutil
import subprocess
import time
import urllib.parse
import uuid

import i18n
import kernel
import paths
import settings
from llm import LLM, Unavailable, instructions, register

log = logging.getLogger("llm")

CODEX_INSTRUCTIONS = """
Each message starts with <now>…</now>, the current date and time: use them only
when asked about them and don't mention them otherwise. You have no terminal and no
files: only the tools you are given."""

TOOL_INSTRUCTIONS = """
You have tools to look up the user's services: use them when needed and sum up
the result in one or two sentences to be said out loud.
For actions that change data, don't ask for confirmation yourself: call the tool.
If the call is rejected, it is waiting for the user's confirmation: ask them in one
short sentence whether to do it (say what you are going to do). If they answer yes,
call exactly the same tool again with the same arguments; if not, don't do it.
Only ask beforehand if it isn't clear what to do (which emails, which day…)."""

FILLER_AFTER = 1.2  # seconds a tool may take before a filler is said
RETRIES = 2  # Codex's own reconnection attempts to wait for before saying there is no connection
EFFORT = "low"  # its reasoning: more makes the first word wait

# An empty folder as its workspace: no project, no AGENTS.md, nothing to read or write.
EMPTY = paths.CACHE / "codex-empty"

# Codex's own tools and extras that reach files, the shell or the computer, or aren't for a
# voice: off. Not «code_mode_host»: Codex calls the MCP tools through it.
OFF = ("shell_tool", "unified_exec", "view_image", "apps", "plugins", "remote_plugin", "browser_use",
       "browser_use_external", "computer_use", "in_app_browser", "multi_agent", "multi_agent_v2",
       "image_generation", "goals", "tool_suggest", "skill_search", "skill_mcp_dependency_install",
       "sleep_tool", "workspace_dependencies", "memories")

NAME, LOGIN = "Codex", "codex login"


def command() -> str | None:
    return shutil.which("codex")


def own_tools(device: str | None) -> dict | None:
    """Jarvis's MCP server for Codex (`mcp_servers.anyassistant`), if permissions.json allows it."""
    try:
        allowed = json.loads(paths.PERMISSIONS.read_text()).get("allowed", {})
    except (OSError, ValueError):
        return None
    if "anyassistant" not in allowed:
        return None
    url = f"http://127.0.0.1:{settings.get('port', 8080)}/mcp"
    server = {"url": f"{url}?device={urllib.parse.quote(device)}" if device else url}
    if isinstance(allowed["anyassistant"], list):
        server["enabled_tools"] = allowed["anyassistant"]
    return server


def trouble(error: dict | None) -> str:
    """What went wrong, from a Codex error (TurnError: codexErrorInfo, its HTTP status):
    «signed_out», «limit», «offline» or «failed»."""
    info = (error or {}).get("codexErrorInfo")
    status = next((v.get("httpStatusCode") for v in info.values() if isinstance(v, dict)), None) \
        if isinstance(info, dict) else None
    if info == "unauthorized" or status in (401, 403):
        return "signed_out"
    if info in ("usageLimitExceeded", "rateLimitExceeded", "sessionBudgetExceeded") or status == 429:
        return "limit"
    if isinstance(info, dict) and {"httpConnectionFailed", "responseStreamConnectionFailed"} & info.keys() \
            and status is None:
        return "offline"
    return "failed"


def sentence(what: str) -> str:
    """What to say about it."""
    if what == "signed_out":
        return i18n.L("speech.llm_signed_out", name=NAME, command=LOGIN)
    if what in ("limit", "offline"):
        return i18n.L(f"speech.llm_{what}", name=NAME)
    if what == "cut":
        return i18n.L("speech.llm_cut", name=NAME)
    return i18n.L("speech.llm_failed")


@register("codex")
class Codex(LLM):
    spoken = ["codex", "códex", "codec", "códec", "kodex", "cotex"]

    @classmethod
    def ready(cls):
        found = command()
        if not found:
            return i18n.L.text("llm_ready.codex", "Codex isn't installed")
        try:
            signed = subprocess.run([found, "login", "status"], capture_output=True, timeout=10).returncode == 0
        except (OSError, subprocess.TimeoutExpired):
            signed = False
        return None if signed else i18n.L.text("llm_ready.codex_login", "Codex isn't signed in")

    def __init__(self, model=None, mcp=None):
        super().__init__(model, mcp)
        EMPTY.mkdir(parents=True, exist_ok=True)
        self._process = None
        self._arguments_for = None  # what the process was started with
        self._ids = itertools.count(1)
        self._waiting: dict[int, asyncio.Future] = {}  # requests sent, by id
        self._events: asyncio.Queue | None = None  # Codex's notifications, for the turn reading them
        self._thread = None  # the conversation
        self._spare = None  # (thread, instructions): the next conversation's, already made
        self._turn = asyncio.Lock()

    # The process and its protocol

    def _arguments(self) -> list[str]:
        arguments = ["app-server"]
        for feature in OFF:
            arguments += ["--disable", feature]
        for key, value in (own_tools(getattr(self, "device", None)) or {}).items():
            arguments += ["-c", f"mcp_servers.anyassistant.{key}={json.dumps(value)}"]  # TOML, as JSON writes it
        return arguments

    def _alive(self) -> bool:
        return self._process is not None and self._process.returncode is None

    async def _start(self):
        await self._stop()
        arguments = self._arguments()
        self._events = asyncio.Queue()
        self._process = await asyncio.create_subprocess_exec(
            command() or "codex", *arguments,
            cwd=EMPTY,
            env={**os.environ, **paths.environment()},
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            limit=1 << 24,  # a whole turn's items, images included, come in one line
        )
        self._arguments_for = arguments
        asyncio.ensure_future(self._read(self._process, self._events))
        asyncio.ensure_future(self._errors(self._process))
        await self._request("initialize", {"clientInfo": {"name": "anyassistant", "title": "AnyAssistant", "version": "1"},
                                           "capabilities": {"experimentalApi": True, "requestAttestation": False}})
        self._send({"method": "initialized"})

    async def _stop(self):
        process, self._process = self._process, None
        self._thread = self._spare = None
        if process and process.returncode is None:
            process.stdin.close()
            try:
                await asyncio.wait_for(process.wait(), 2)
            except asyncio.TimeoutError:
                process.kill()

    async def close(self):
        await self._stop()

    async def _errors(self, process):
        async for line in process.stderr:
            log.debug("codex: %s", line.decode(errors="replace").rstrip())

    def _send(self, message: dict):
        self._process.stdin.write(json.dumps({"jsonrpc": "2.0", **message}).encode() + b"\n")

    async def _request(self, method: str, params: dict, timeout: float = 60):
        if not self._alive():
            raise ConnectionError("Codex isn't running")
        number = next(self._ids)
        future = self._waiting[number] = asyncio.get_running_loop().create_future()
        self._send({"id": number, "method": method, "params": params})
        await self._process.stdin.drain()
        try:
            return await asyncio.wait_for(future, timeout)
        finally:
            self._waiting.pop(number, None)

    async def _read(self, process, events: asyncio.Queue):
        """Codex's messages: answers to requests, its own requests (approvals), notifications."""
        while True:
            line = await process.stdout.readline()
            if not line:
                break
            try:
                message = json.loads(line)
            except ValueError:
                continue
            if "method" not in message:  # the answer to a request
                future = self._waiting.get(message.get("id"))
                if future and not future.done():
                    if "error" in message:
                        future.set_exception(RuntimeError(str(message["error"].get("message"))))
                    else:
                        future.set_result(message.get("result"))
            elif "id" in message:  # it asks something
                self._answer(process, message)
            else:
                events.put_nowait(message)
        for future in list(self._waiting.values()):
            if not future.done():
                future.set_exception(ConnectionError("Codex stopped"))
        events.put_nowait(None)

    def _answer(self, process, request: dict):
        """Codex's requests: an MCP tool's approval goes through the plugin «confirmation»; it gets
        nothing else (commands and file changes can't happen: no tools for them)."""
        method, params = request["method"], request.get("params") or {}
        result = None
        if method == "mcpServer/elicitation/request":
            meta = params.get("_meta") or {}
            yes = False
            if meta.get("codex_approval_kind") == "mcp_tool_call":
                yes = self._let_through(params.get("serverName", ""), params.get("message", ""),
                                        meta.get("tool_params") or {})
            # Anything else (an MCP server's own form or sign-in link) isn't for a voice: declined.
            result = {"action": "accept", "content": {}, "_meta": None} if yes else \
                {"action": "decline", "content": None, "_meta": None}
        elif method in ("item/commandExecution/requestApproval", "item/fileChange/requestApproval",
                        "execCommandApproval", "applyPatchApproval"):
            log.warning("Codex asked to %s: refused", method)
            result = {"decision": "decline"} if method.startswith("item/") else \
                {"decision": {"denied": {"rejection": "Jarvis allows no commands or file changes"}}}
        if result is None:
            reply = {"id": request["id"], "error": {"code": -32601, "message": f"not supported: {method}"}}
        else:
            reply = {"id": request["id"], "result": result}
        if process.returncode is None:
            process.stdin.write(json.dumps({"jsonrpc": "2.0", **reply}).encode() + b"\n")

    @staticmethod
    def _let_through(server: str, message: str, arguments: dict) -> bool:
        """«Allow the holded MCP server to run tool "create_invoice"?»: with your «yes» to it."""
        tool = message.split('tool "', 1)[1].split('"', 1)[0] if 'tool "' in message else message
        confirmation = kernel.module("confirmation")
        yes = confirmation is None or confirmation.let_through(server, tool, arguments)  # off: nothing asks
        log.info("Codex wants %s: %s: %s", "and may" if yes else "to wait for a «yes»", server, tool)
        return yes

    # Conversations

    def _instructions(self) -> str:
        eyes = kernel.module("eyes")
        text = instructions() + CODEX_INSTRUCTIONS + (eyes.seeing() if eyes else "")
        return text + TOOL_INSTRUCTIONS

    async def _new_thread(self, text: str) -> str:
        params = {"cwd": str(EMPTY), "approvalPolicy": "on-request", "sandbox": "read-only", "ephemeral": True,
                  "baseInstructions": text}
        if self.model:
            params["model"] = self.model
        return (await self._request("thread/start", params))["thread"]["id"]

    async def _ready(self):
        """The process (again if what it was started with changed) and a conversation."""
        if not self._alive() or self._arguments_for != self._arguments():
            await self._start()
        if not self._thread:
            text = self._instructions()
            spare, self._spare = self._spare, None
            self._thread = spare[0] if spare and spare[1] == text else await self._new_thread(text)

    async def prepare(self):
        """The next conversation's thread, with the current instructions (memory, settings…)."""
        async with self._turn:
            try:
                if not self._alive() or self._arguments_for != self._arguments():
                    await self._start()
                text = self._instructions()
                if not self._spare or self._spare[1] != text:
                    self._spare = (await self._new_thread(text), text)
            except (ConnectionError, RuntimeError, asyncio.TimeoutError) as e:
                log.warning("Codex couldn't get ready: %s", e)

    async def new(self):
        """Another thread (Codex keeps nothing: ephemeral), made now, while the question is said."""
        async with self._turn:
            self._thread = None
            try:
                await self._ready()
            except (ConnectionError, RuntimeError, asyncio.TimeoutError) as e:
                log.warning("Codex couldn't get ready: %s", e)  # the answer tries again

    async def reload(self):
        async with self._turn:
            await self._stop()

    async def answer(self, text: str, image: bytes | None = None):
        async with self._turn:
            try:
                await self._ready()
            except (ConnectionError, RuntimeError, asyncio.TimeoutError) as e:
                log.warning("Codex didn't start: %s", e)
                await self._stop()
                raise Unavailable(sentence("cut")) from None
            while not self._events.empty():  # leftovers of an earlier turn
                self._events.get_nowait()
            content = [{"type": "text", "text": f"<now>{i18n.L.now_spoken()}</now>\n{text}", "text_elements": []}]
            if image:
                content.append({"type": "image", "url": "data:image/jpeg;base64," + base64.b64encode(image).decode()})
            try:
                turn = (await self._request("turn/start", {"threadId": self._thread, "input": content,
                                                           "effort": EFFORT}))["turn"]["id"]
            except (ConnectionError, RuntimeError, asyncio.TimeoutError) as e:
                log.warning("Codex refused the turn: %s", e)
                await self._stop()
                raise Unavailable(sentence("cut")) from None
            async for piece in self._pieces(turn):
                yield piece

    async def _pieces(self, turn: str):
        said = False
        # A tool started before any text: if it takes a while, a filler («Let me look.»); if it
        # ends at once (or waits for your «yes»), nothing.
        filler_at = None
        retries = 0
        reading = None
        while True:
            reading = reading or asyncio.ensure_future(self._events.get())
            wait = None if filler_at is None else max(filler_at - time.time(), 0)
            done, _ = await asyncio.wait({reading}, timeout=wait)
            if not done:
                filler_at, said = None, True
                yield i18n.L("speech.wait") + " "
                continue
            event, reading = reading.result(), None
            if event is None:  # the process died: the next message starts another
                raise Unavailable(sentence("cut"))
            method, params = event.get("method"), event.get("params") or {}
            if params.get("turnId", turn) != turn:
                continue
            item = params.get("item") or {}
            if method == "item/agentMessage/delta":
                if params.get("delta"):
                    said, filler_at = True, None
                    yield params["delta"]
            elif method == "item/started" and item.get("type") == "agentMessage" and said:
                yield " "  # a new message after a tool: without the space it sticks to the last one
            elif method == "item/started" and item.get("type") in ("mcpToolCall", "webSearch"):
                name = f"mcp__{item.get('server')}__{item.get('tool')}" if item["type"] == "mcpToolCall" else "web_search"
                log.info("tool: %s", name)
                self.on_tool(name, item.get("arguments") or {})
                if not said and settings.get("fillers", True):
                    filler_at = time.time() + FILLER_AFTER
            elif method == "item/completed" and item.get("type") in ("mcpToolCall", "webSearch"):
                filler_at = None
            elif method == "error":
                error = params.get("error") or {}
                log.warning("Codex error: %s %s", error.get("message"), error.get("additionalDetails") or "")
                if params.get("willRetry"):  # without it, turn/completed (failed) follows
                    what = trouble(error)
                    retries += 1
                    # Retrying may help a hiccup, or a short cut of the connection; not being signed
                    # out or over its limit.
                    if what == "failed" or what == "offline" and retries <= RETRIES:
                        continue
                    await self._interrupt(turn)
                    await self._fail(what)
            elif method == "turn/completed":
                found = params.get("turn") or {}
                if found.get("status") == "failed":
                    log.warning("Codex failed: %s", found.get("error"))
                    await self._fail(trouble(found.get("error")))
                return

    async def _fail(self, what: str):
        if what == "signed_out":
            await self._stop()  # it stays useless even after signing in again: the next one starts another
        raise Unavailable(sentence(what))

    async def _interrupt(self, turn: str):
        try:
            await self._request("turn/interrupt", {"threadId": self._thread, "turnId": turn}, timeout=5)
        except (ConnectionError, RuntimeError, asyncio.TimeoutError):
            pass

    async def complete(self, prompt: str) -> str:
        """A one-off `codex exec`: without your Codex settings, its MCP servers or any tool."""
        out = EMPTY / f"complete-{uuid.uuid4().hex[:8]}.txt"
        arguments = ["exec", "--ephemeral", "--skip-git-repo-check", "--ignore-user-config", "--ignore-rules",
                     "--sandbox", "read-only", "--color", "never", "--cd", str(EMPTY),
                     "-c", f"model_reasoning_effort={json.dumps(EFFORT)}", "--output-last-message", str(out)]
        for feature in OFF:
            arguments += ["--disable", feature]
        if self.model:
            arguments += ["--model", self.model]
        process = await asyncio.create_subprocess_exec(
            command() or "codex", *arguments, "-", cwd=EMPTY, stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
        try:
            _, err = await asyncio.wait_for(process.communicate(prompt.encode()), 180)
            if process.returncode:
                raise RuntimeError(err.decode(errors="replace")[-300:])
            return out.read_text().strip()
        finally:
            out.unlink(missing_ok=True)
