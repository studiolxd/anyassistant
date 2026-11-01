"""LLMs through the Agent Client Protocol (ACP: JSON-RPC over stdin/stdout, how editors talk to
coding agents): the base of the plugins «llm-gemini» (`gemini --acp`) and «llm-opencode»
(`opencode acp`), each with your account in it. A subclass says how to start it, what its
permission requests are about and what its errors mean.

One process per device's LLM, kept between conversations, a session for each (new()); the answer
in pieces (session/update agent_message_chunk), so the voice starts before it ends; the camera's
image goes with the question that looked.

Its tools: before one, the agent asks (session/request_permission) and waits for the answer:
- its own tools (files, terminal, web fetch…: what tool() doesn't take for an MCP call): refused;
- MCP tools that only read (get_, list_…) and Jarvis's own (they ask for your «yes» themselves):
  allowed, as Claude's hook does;
- anything else: Jarvis asks you aloud («Gemini wants to do this: … Shall I?») while the agent
  waits, and your «yes» (the plugin «confirmation», the same as always) allows exactly that call,
  once; anything else refuses it. (Unlike Codex, the agent can't be told «ask and try again»:
  OpenCode doesn't say which tool a code-mode call is for, and refusing may end its turn.)
"""

import asyncio
import base64
import itertools
import json
import logging
import os
import time
from pathlib import Path

import i18n
import kernel
import paths
import settings
from llm import LLM, Unavailable, instructions

log = logging.getLogger("llm")

ACP_INSTRUCTIONS = """
Each message starts with <now>…</now>, the current date and time: use them only
when asked about them and don't mention them otherwise. You have no terminal and
no files here, only the tools you are given: don't try to read or run anything else.
Use the tools when needed and sum up the result in one or two sentences to be said
out loud. For actions that change data, don't ask for confirmation yourself: call the
tool, and the system asks the user and waits. If a tool call is refused or canceled,
the user said no: don't try it again unless they ask."""

FILLER_AFTER = 1.2  # seconds a tool may take before a filler is said


class ACP(LLM):
    NAME = "?"  # how it is named when something is said about it
    LOGIN = "?"  # what signs in, said when it is signed out
    SENTENCES: dict[str, str] = {}  # its own kinds of trouble (trouble()) → their locale key
    folder: Path = paths.CACHE / "acp-empty"  # its workspace: an empty folder of its own

    # What a subclass says

    def command(self) -> list[str]:
        """How to start it (in ACP mode)."""
        raise NotImplementedError

    def environment(self) -> dict:
        """More environment for it (its configuration for this run)."""
        return {}

    def servers(self) -> list[dict]:
        """MCP servers for a new session (ACP's format)."""
        return []

    def text(self) -> str:
        """Its instructions: Jarvis's, the camera's (what its image is) and how to use the tools."""
        eyes = kernel.module("eyes")
        return instructions() + ACP_INSTRUCTIONS + (eyes.seeing() if eyes else "")

    def preamble(self) -> str:
        """Text before the first message of each session (the instructions, if it has no other way
        to get them)."""
        return ""

    def before_session(self):
        """Just before a new session (e.g. writing its instructions where it reads them)."""

    def tool(self, call: dict) -> tuple[str, str, dict, str] | None:
        """What a permission request is about: (MCP server, tool, arguments, the action in words), or
        None for one of its own tools (refused)."""
        return None

    def trouble(self, message: str) -> str:
        """What an error means: «signed_out», «limit», «offline», one of SENTENCES or «failed»."""
        return "failed"

    async def configure(self, session: str):
        """A new session, before it is used (its model…)."""

    # The process and its protocol

    def __init__(self, model=None, mcp=None):
        super().__init__(model, mcp)
        self.folder.mkdir(parents=True, exist_ok=True)
        self._process = None
        self._started_with = None
        self._ids = itertools.count(1)
        self._waiting: dict[int, asyncio.Future] = {}  # requests sent, by id
        self._queues: dict[str, asyncio.Queue] = {}  # each session's updates, for the turn reading them
        self._quiet: set[str] = set()  # complete()'s sessions: no tools at all
        self._asking: set[str] = set()  # the tools waiting for your «yes» (their signatures)
        self._session = None  # the conversation
        self._first = False  # its next message is its first one
        self._spare = None  # (session, instructions): the next conversation's, already made
        self._turn = asyncio.Lock()

    def sentence(self, what: str) -> str:
        if what == "signed_out":
            return i18n.L("speech.llm_signed_out", name=self.NAME, command=self.LOGIN)
        if what in ("limit", "offline"):
            return i18n.L(f"speech.llm_{what}", name=self.NAME)
        if what == "cut":
            return i18n.L("speech.llm_cut", name=self.NAME)
        if what in self.SENTENCES:
            return i18n.L(self.SENTENCES[what], name=self.NAME, command=self.LOGIN)
        return i18n.L("speech.llm_failed")

    def _start_with(self) -> tuple:
        return (tuple(self.command()), tuple(sorted(self.environment().items())))

    def _alive(self) -> bool:
        return self._process is not None and self._process.returncode is None

    async def _start(self):
        await self._stop()
        self._started_with = self._start_with()
        command = self.command()
        self._process = await asyncio.create_subprocess_exec(
            *command,
            cwd=self.folder,
            env={**os.environ, **paths.environment(), **self.environment()},
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            limit=1 << 24,
        )
        asyncio.ensure_future(self._read(self._process))
        asyncio.ensure_future(self._errors(self._process))
        await self._request("initialize", {
            "protocolVersion": 1,
            "clientCapabilities": {"fs": {"readTextFile": False, "writeTextFile": False}, "terminal": False},
            "clientInfo": {"name": "anyassistant", "title": "AnyAssistant", "version": "1"}})

    async def _stop(self):
        process, self._process = self._process, None
        self._session = self._spare = None
        self._queues.clear()
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
            line = line.decode(errors="replace").rstrip()
            log.debug("%s: %s", self.NAME, line)
            self.stderr(line)

    def stderr(self, line: str):
        """A line it wrote to stderr (a subclass may watch for something)."""

    def _write(self, process, message: dict):
        if process.returncode is None:
            process.stdin.write(json.dumps({"jsonrpc": "2.0", **message}).encode() + b"\n")

    async def _request(self, method: str, params: dict, timeout: float | None = 60):
        if not self._alive():
            raise ConnectionError(f"{self.NAME} isn't running")
        number = next(self._ids)
        future = self._waiting[number] = asyncio.get_running_loop().create_future()
        self._write(self._process, {"id": number, "method": method, "params": params})
        await self._process.stdin.drain()
        try:
            return await asyncio.wait_for(future, timeout)
        finally:
            self._waiting.pop(number, None)

    async def _read(self, process):
        """Its messages: answers to requests, its own requests (permissions), session updates."""
        while True:
            line = await process.stdout.readline()
            if not line:
                break
            try:
                message = json.loads(line)
            except ValueError:
                continue  # a stray line (some agents print logs on stdout)
            if "method" not in message:  # the answer to a request
                future = self._waiting.get(message.get("id"))
                if future and not future.done():
                    if "error" in message:
                        error = message["error"] or {}
                        future.set_exception(RuntimeError(str(error.get("message") or error)))
                    else:
                        future.set_result(message.get("result"))
            elif "id" in message:  # it asks something: it may wait for your «yes»
                asyncio.ensure_future(self._asked(process, message))
            elif message["method"] == "session/update":
                params = message.get("params") or {}
                queue = self._queues.get(params.get("sessionId"))
                if queue:
                    queue.put_nowait(params.get("update") or {})
        for future in list(self._waiting.values()):
            if not future.done():
                future.set_exception(ConnectionError(f"{self.NAME} stopped"))
        for queue in self._queues.values():
            queue.put_nowait(None)

    async def _asked(self, process, request: dict):
        if request["method"] != "session/request_permission":  # files, terminal: it has neither
            log.warning("%s asked for %s: refused", self.NAME, request["method"])
            self._write(process, {"id": request["id"], "error": {"code": -32601, "message": "not supported"}})
            return
        params = request.get("params") or {}
        yes = await self._permission(params)
        options = params.get("options") or []
        wanted = ("allow_once", "allow_always") if yes else ("reject_once", "reject_always")
        option = next((o["optionId"] for kind in wanted for o in options if o.get("kind") == kind), None)
        outcome = {"outcome": "selected", "optionId": option} if option else {"outcome": "cancelled"}
        self._write(process, {"id": request["id"], "result": {"outcome": outcome}})

    async def _permission(self, params: dict) -> bool:
        """Whether the tool it asks for may run: see the module's docstring."""
        session, call = params.get("sessionId"), params.get("toolCall") or {}
        found = None if session in self._quiet else self.tool(call)
        if found is None:
            log.info("%s wanted one of its own tools: refused (%s)", self.NAME, call.get("title"))
            return False
        server, name, arguments, action = found
        confirmation = kernel.module("confirmation")
        if confirmation is None or confirmation.free(server, name):  # off: nothing asks
            log.info("%s uses %s: %s", self.NAME, server, name)
            return True
        log.info("%s wants to (your «yes» first): %s", self.NAME, settings.private(action))
        queue = self._queues.get(session)
        if queue:
            queue.put_nowait({"sessionUpdate": "anyassistant_question",
                              "text": i18n.L("speech.llm_approval", name=self.NAME, action=action)})
        sign = confirmation.store.signature(f"mcp__{server}__{name}", arguments, call.get("toolCallId"))
        self._asking.add(sign)
        try:
            yes = await confirmation.decision(sign, f"{self.NAME}: {action}")
        finally:
            self._asking.discard(sign)
        log.info("%s: %s", self.NAME, "allowed" if yes else "refused")
        return yes

    # Conversations

    async def _new_session(self, quiet: bool = False) -> str:
        self.before_session()
        result = await self._request("session/new", {"cwd": str(self.folder), "mcpServers": [] if quiet else self.servers()})
        session = result["sessionId"]
        if quiet:
            self._quiet.add(session)
        await self.configure(session)
        return session

    def _instructions_now(self) -> str:
        """What the session is made with: if it changes (memory…), the spare is no good."""
        return self.text() + json.dumps(self._start_with())

    async def _ready(self):
        """The process (again if what it is started with changed) and a conversation."""
        if not self._alive() or self._started_with != self._start_with():
            await self._start()
        if not self._session:
            now = self._instructions_now()
            spare, self._spare = self._spare, None
            self._session = spare[0] if spare and spare[1] == now else await self._new_session()
            self._first = True

    async def prepare(self):
        """The next conversation's session, with the current instructions."""
        async with self._turn:
            try:
                if not self._alive() or self._started_with != self._start_with():
                    await self._start()
                now = self._instructions_now()
                if not self._spare or self._spare[1] != now:
                    self._spare = (await self._new_session(), now)
            except (ConnectionError, RuntimeError, asyncio.TimeoutError) as e:
                log.warning("%s couldn't get ready: %s", self.NAME, e)

    async def new(self):
        """Another session (it forgets the last one), made now, while the question is said."""
        async with self._turn:
            self._session = None
            try:
                await self._ready()
            except (ConnectionError, RuntimeError, asyncio.TimeoutError) as e:
                log.warning("%s couldn't get ready: %s", self.NAME, e)  # the answer tries again

    async def reload(self):
        async with self._turn:
            await self._stop()

    async def _failed(self, error: Exception):
        """Why it couldn't answer, to say it; dead or signed out, it starts again next time."""
        if isinstance(error, (ConnectionError, asyncio.TimeoutError)):
            what = "cut"
        else:
            what = self.trouble(str(error))
        log.warning("%s: %s (%s)", self.NAME, error, what)
        if what in ("cut", "signed_out") or what in self.SENTENCES:
            await self._stop()
        raise Unavailable(self.sentence(what)) from None

    def _blocks(self, text: str, image: bytes | None) -> list[dict]:
        blocks = [{"type": "text", "text": text}]
        if image:
            blocks.append({"type": "image", "mimeType": "image/jpeg", "data": base64.b64encode(image).decode()})
        return blocks

    async def answer(self, text: str, image: bytes | None = None):
        async with self._turn:
            try:
                await self._ready()
            except (ConnectionError, RuntimeError, asyncio.TimeoutError) as e:
                await self._failed(e)
            text = f"<now>{i18n.L.now_spoken()}</now>\n{text}"
            if self._first:
                text = f"{self.preamble()}\n\n{text}" if self.preamble() else text
            self._first = False
            queue = self._queues[self._session] = asyncio.Queue()
            prompt = asyncio.ensure_future(self._request(
                "session/prompt", {"sessionId": self._session, "prompt": self._blocks(text, image)}, timeout=None))
            try:
                async for piece in self._pieces(queue, prompt):
                    yield piece
            finally:
                if not prompt.done():  # cut off: it stops, and the session stays usable
                    prompt.cancel()
                    if self._alive():
                        self._write(self._process, {"method": "session/cancel", "params": {"sessionId": self._session}})
                    confirmation = kernel.module("confirmation")
                    for sign in list(self._asking):  # nobody hears that question any more
                        if confirmation and confirmation.store.waiting(sign):
                            confirmation.store.answer(False)

    async def _pieces(self, queue: asyncio.Queue, prompt: asyncio.Future):
        said = after_tool = False
        # A tool started before any text: if it takes a while, a filler («Let me look.»).
        filler_at = None
        reading = None
        while True:
            reading = reading or asyncio.ensure_future(queue.get())
            wait = None if filler_at is None else max(filler_at - time.time(), 0)
            done, _ = await asyncio.wait({reading, prompt}, timeout=wait, return_when=asyncio.FIRST_COMPLETED)
            if not done:
                filler_at, said = None, True
                yield i18n.L("speech.wait") + " "
                continue
            if reading not in done:  # the turn ended: what came before it, then its result
                reading.cancel()
                while not queue.empty():
                    update = queue.get_nowait()
                    if update and update.get("sessionUpdate") == "agent_message_chunk":
                        piece = (update.get("content") or {}).get("text") or ""
                        said = said or bool(piece)
                        yield piece
                try:
                    result = prompt.result() or {}
                except (ConnectionError, RuntimeError, asyncio.TimeoutError) as e:
                    await self._failed(e)
                if result.get("stopReason") in ("cancelled", "refusal") and not said:
                    log.warning("%s stopped: %s", self.NAME, result.get("stopReason"))
                    raise Unavailable(i18n.L("speech.llm_failed"))
                return
            update, reading = reading.result(), None
            if update is None:  # the process died: the next message starts another
                await self._failed(ConnectionError("stopped"))
            kind = update.get("sessionUpdate")
            if kind == "agent_message_chunk":
                piece = (update.get("content") or {}).get("text") or ""
                if piece:
                    if after_tool and said and not piece[:1].isspace():
                        piece = " " + piece  # new text after a tool: without the space it sticks
                    said, after_tool, filler_at = True, False, None
                    yield piece
            elif kind == "anyassistant_question":  # a tool waits for your «yes»
                said, filler_at = True, None
                yield " " + update["text"] + " "
            elif kind == "tool_call":
                name = update.get("title") or update.get("kind") or "?"
                log.info("tool: %s", name)
                self.on_tool(name, update.get("rawInput") or {})
                after_tool = True
                if not said and settings.get("fillers", True):
                    filler_at = time.time() + FILLER_AFTER
            elif kind == "tool_call_update" and update.get("status") in ("completed", "failed"):
                filler_at = None

    async def complete(self, prompt: str) -> str:
        """One answer outside the conversation: a session of its own, without tools."""
        async with self._turn:
            try:
                if not self._alive() or self._started_with != self._start_with():
                    await self._start()
                session = await self._new_session(quiet=True)
            except (ConnectionError, RuntimeError, asyncio.TimeoutError) as e:
                await self._failed(e)
            queue = self._queues[session] = asyncio.Queue()
            try:
                await self._request("session/prompt", {"sessionId": session, "prompt": self._blocks(prompt, None)},
                                    timeout=180)
            except (ConnectionError, RuntimeError, asyncio.TimeoutError) as e:
                await self._failed(e)
            finally:
                self._queues.pop(session, None)
                self._quiet.discard(session)
            pieces = []
            while not queue.empty():
                update = queue.get_nowait()
                if update and update.get("sessionUpdate") == "agent_message_chunk":
                    pieces.append((update.get("content") or {}).get("text") or "")
            return "".join(pieces).strip()


def own_tools(device: str | None) -> tuple[str, list[str] | None] | None:
    """Jarvis's MCP server, if permissions.json allows «anyassistant»: (its URL, only these tools or None)."""
    import urllib.parse

    try:
        allowed = json.loads(paths.PERMISSIONS.read_text()).get("allowed", {})
    except (OSError, ValueError):
        return None
    if "anyassistant" not in allowed:
        return None
    url = f"http://127.0.0.1:{settings.get('port', 8080)}/mcp"
    url = f"{url}?device={urllib.parse.quote(device)}" if device else url
    tools = allowed["anyassistant"]
    return url, tools if isinstance(tools, list) else None


def spoken(tool: str, arguments: dict) -> str:
    """«send_note» {"text": "hola"} → «send note: hola», to be said."""
    values = ", ".join(str(v) for v in arguments.values() if v not in (None, "", [], {}))
    said = tool.replace("_", " ") + (f": {values}" if values else "")
    return said if len(said) <= 200 else said[:200] + "…"
