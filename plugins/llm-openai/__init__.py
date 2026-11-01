"""LLMs that speak OpenAI's API (/v1/chat/completions): one plugin, a profile each.

- «openai»: OpenAI (https://api.openai.com/v1), or any compatible service at «openai_url»
  (OpenRouter, Groq, Mistral, LM Studio…). Its key: OPENAI_API_KEY, or the keychain
  (`bin/anyassistant llm-key openai`). The model: «llm_model» (default gpt-5-mini).
- «ollama»: the models running on this computer with Ollama (http://localhost:11434/v1, no key);
  «llm_model», or the first one installed.
- «hermes»: Hermes Agent through its API gateway (HERMES_API_URL, default http://127.0.0.1:8642;
  its key, API_SERVER_KEY in ~/.hermes/.env or HERMES_API_KEY).

How they differ:
- The conversation: OpenAI's API keeps nothing, so Jarvis keeps it (each device's, sent again with
  every question; a new conversation forgets it). Hermes keeps its own (a session id).
- The tools: «openai» and «ollama» get Jarvis's own (timers, settings, memory, mail…): the model
  asks for one, Jarvis runs it and gives back the result; those that change something wait for
  your «yes», as with any LLM (the plugin «confirmation»). Hermes uses its own tools and, when it
  wants to do something, asks for approval: Jarvis asks you and answers it (once, or deny).
- The camera's image goes with the question that looked (OpenAI's format), and they are told
  what it is (eyes.seeing: its left is your right).
"""

import asyncio
import base64
import json
import logging
import os
import time
import uuid
from pathlib import Path

import i18n
import keychain
import kernel
import options
import settings
import tools
from llm import LLM, Unavailable, instructions, register
from options import Option

log = logging.getLogger("llm")
TOOL_ROUNDS = 6  # tool calls in a row, at most, before answering
KEYCHAIN = "AnyAssistant LLM"

options.add(Option("openai_key", None, "the API key for «openai» (saved in the system's keychain)", "assistant",
                   kind="secret", keychain=(KEYCHAIN, "openai"), live=True))
options.add(Option("openai_url", None, "the OpenAI-compatible service for «openai» (OpenRouter, Groq, LM Studio…)",
                   "assistant", empty="https://api.openai.com/v1"))


def _seeing() -> str:
    """With the plugin «eyes»: what the camera's image is (its left is the user's right)."""
    eyes = kernel.module("eyes")
    return eyes.seeing() if eyes else ""


class Chat(LLM):
    """What every profile shares: /v1/chat/completions, streamed; the camera's image."""
    url = ""
    session_header = ""  # Hermes: its session id (it keeps the conversation)
    own_tools = True  # Jarvis's tools (not Hermes: it has its own)

    def __init__(self, model=None, mcp=None):
        super().__init__(model, mcp)
        self._http = None
        self._turn = asyncio.Lock()
        self._messages: list[dict] = []  # the conversation, when Jarvis keeps it
        self._session = None

    def key(self) -> str | None:
        return None

    async def _client(self):
        import aiohttp

        if self._http is None or self._http.closed:
            key = self.key()
            self._http = aiohttp.ClientSession(
                headers={"Authorization": f"Bearer {key}"} if key else {},
                timeout=aiohttp.ClientTimeout(total=None, sock_connect=5, sock_read=120))
        return self._http

    async def new(self):
        self._messages = []
        self._session = f"anyassistant-{uuid.uuid4().hex[:12]}"

    async def close(self):
        if self._http and not self._http.closed:
            await self._http.close()

    def _model(self) -> str:
        return self.model or "default"

    @staticmethod
    def _content(text: str, image: bytes | None):
        """The message, with the camera's image if it looked."""
        if not image:
            return text
        url = "data:image/jpeg;base64," + base64.b64encode(image).decode()
        return [{"type": "text", "text": text}, {"type": "image_url", "image_url": {"url": url}}]

    def _tools(self) -> list[dict]:
        if not self.own_tools:
            return []
        return [{"type": "function", "function": {"name": name, "description": t.description, "parameters": t.schema}}
                for name, t in tools.available().items()]

    def _system(self) -> dict:
        return {"role": "system", "content": instructions() + _seeing()}

    async def answer(self, text: str, image: bytes | None = None):
        async with self._turn:
            if not self._session:
                await self.new()
            asked = {"role": "user", "content": self._content(text, image)}
            if self.session_header:  # it keeps the conversation: only this question
                messages = [self._system(), asked]
            else:
                self._messages.append(asked)
                messages = None
            said = False
            for _ in range(TOOL_ROUNDS):
                body = {"model": self._model(), "stream": True,
                        "messages": messages or [self._system(), *self._messages]}
                offered = self._tools()
                if offered:
                    body["tools"] = offered
                pieces, calls = [], {}
                async for kind, value in self._stream(body):
                    if kind == "text":
                        said = True
                        pieces.append(value)
                        yield value
                    elif kind == "call":  # a piece of a tool call: its name, its arguments in parts
                        index = value.get("index", 0)
                        call = calls.setdefault(index, {"id": "", "name": "", "arguments": ""})
                        call["id"] = value.get("id") or call["id"]
                        function = value.get("function") or {}
                        call["name"] += function.get("name") or ""
                        call["arguments"] += function.get("arguments") or ""
                    elif kind == "say":  # Hermes: its approval question
                        said = True
                        yield value
                    elif kind == "busy" and not said and settings.get("fillers", True):  # Hermes uses a tool
                        said = True
                        yield i18n.L("speech.wait") + " "
                if not calls:
                    if not self.session_header:
                        self._messages.append({"role": "assistant", "content": "".join(pieces)})
                    break
                # The model asked for tools: Jarvis runs them, the results go back, and it goes on.
                self._messages.append({"role": "assistant", "content": "".join(pieces) or None, "tool_calls": [
                    {"id": c["id"], "type": "function", "function": {"name": c["name"], "arguments": c["arguments"] or "{}"}}
                    for c in calls.values()]})
                if not said and settings.get("fillers", True):
                    said = True
                    yield i18n.L("speech.wait") + " "
                for c in calls.values():
                    self._messages.append({"role": "tool", "tool_call_id": c["id"], "content": self._run(c)})
            if image and not self.session_header:  # the image only once: the history keeps the words
                asked["content"] = text

    def _run(self, call: dict) -> str:
        """One of Jarvis's tools, as the model asked (what changes something waits for your «yes»)."""
        name = call["name"]
        self.on_tool(name, call["arguments"])
        try:
            arguments = json.loads(call["arguments"] or "{}")
            result = tools.call(name, arguments if isinstance(arguments, dict) else {})
            log.info("llm tool: %s", name)
            return str(result)
        except (tools.ToolError, ValueError) as e:  # a refusal, «ask for a yes first», wrong arguments
            log.info("llm tool %s: %s", name, e)
            return f"Error: {e}"

    async def _stream(self, body: dict):
        """(«text», a piece) and («call», a tool call's piece), as they come."""
        import aiohttp

        http = await self._client()
        headers = {self.session_header: self._session} if self.session_header else {}
        try:
            async with http.post(self.url.rstrip("/") + "/chat/completions", json=body, headers=headers) as r:
                if r.status != 200:
                    detail = (await r.text())[:300]
                    log.warning("%s answered %s: %s", self.name, r.status, detail)
                    raise Unavailable(i18n.L("speech.llm_key" if r.status in (401, 403) else
                                             "speech.llm_limit" if r.status == 429 else "speech.llm_failed",
                                             name=self.name.title()))
                event = None
                async for line in r.content:
                    line = line.decode().strip()
                    if line.startswith("event:"):
                        event = line[6:].strip()
                        continue
                    if not line.startswith("data:"):
                        event = None if not line else event
                        continue
                    data = line[5:].strip()
                    if data == "[DONE]":
                        return
                    data = json.loads(data)
                    if event:
                        async for found in self._event(event, data):
                            yield found
                    else:
                        delta = (data.get("choices") or [{}])[0].get("delta") or {}
                        if delta.get("content"):
                            yield "text", delta["content"]
                        for call in delta.get("tool_calls") or []:
                            yield "call", call
                    event = None
        except aiohttp.ClientConnectorError:
            raise Unavailable(i18n.L("speech.llm_down", name=self.name.title())) from None

    async def _event(self, event: str, data: dict):
        """A profile's own SSE events (Hermes's): nothing for OpenAI's."""
        return
        yield

    async def complete(self, prompt: str) -> str:
        """One answer outside the conversation (the memory's review, the interpreter)."""
        http = await self._client()
        body = {"model": self._model(), "stream": False, "messages": [{"role": "user", "content": prompt}]}
        async with http.post(self.url.rstrip("/") + "/chat/completions", json=body) as r:
            if r.status != 200:
                raise Unavailable(i18n.L("speech.llm_failed"))
            data = await r.json()
        return (data.get("choices") or [{}])[0].get("message", {}).get("content") or ""


@register("openai")
class OpenAI(Chat):
    spoken = ["openai", "chatgpt", "gpt"]

    @property
    def url(self):
        return settings.get("openai_url") or "https://api.openai.com/v1"

    def key(self):
        return os.environ.get("OPENAI_API_KEY") or keychain.get(KEYCHAIN, "openai")

    @classmethod
    def ready(cls):
        if not (os.environ.get("OPENAI_API_KEY") or keychain.get(KEYCHAIN, "openai")):
            return i18n.L.text("llm_ready.openai", "Needs an API key (Settings → Assistant)")
        return None

    def _model(self):
        return self.model or "gpt-5-mini"


OLLAMA = os.environ.get("OLLAMA_HOST", "http://localhost:11434").rstrip("/")


@register("ollama")
class Ollama(Chat):
    spoken = ["ollama", "olama"]
    url = OLLAMA + "/v1"

    @staticmethod
    def installed() -> list[str]:
        import urllib.request

        try:
            with urllib.request.urlopen(OLLAMA + "/api/tags", timeout=1) as r:
                return [m["name"] for m in json.load(r).get("models", [])]
        except (OSError, ValueError, KeyError):
            return []

    @classmethod
    def ready(cls):
        if not cls.installed():
            return i18n.L.text("llm_ready.ollama", "Ollama isn't running or has no model")
        return None

    def _model(self):
        return self.model or (self.installed() or ["llama3.2"])[0]


HERMES = os.environ.get("HERMES_API_URL", "http://127.0.0.1:8642").rstrip("/")
ENV = Path.home() / ".hermes" / ".env"


def hermes_key() -> str:
    if os.environ.get("HERMES_API_KEY"):
        return os.environ["HERMES_API_KEY"]
    try:
        for line in ENV.read_text().splitlines():
            if line.startswith("API_SERVER_KEY="):
                return line.split("=", 1)[1].strip().strip('"')
    except OSError:
        pass
    raise RuntimeError(f"API_SERVER_KEY missing in {ENV}: enable Hermes's API")


@register("hermes")
class Hermes(Chat):
    spoken = ["hermes"]
    url = HERMES + "/v1"
    session_header = "X-Hermes-Session-Id"  # it keeps the conversation
    own_tools = False  # its own tools; it asks for approval

    def __init__(self, model=None, mcp=None):
        super().__init__(model, mcp)
        self._key = hermes_key()

    def key(self):
        return self._key

    @classmethod
    def ready(cls):
        import urllib.request

        try:
            urllib.request.urlopen(HERMES + "/health", timeout=1)
            return None
        except OSError:
            return i18n.L.text("llm_ready.hermes", "Hermes's gateway isn't running")

    def _model(self):
        return self.model or "hermes-agent"

    async def _event(self, event: str, data: dict):
        if event == "approval.request":
            yield "say", self._approval(data)
        elif event == "hermes.tool.progress":
            log.info("Hermes tool: %s", data.get("tool") or data.get("name"))
            self.on_tool(data.get("tool") or data.get("name") or "?")
            yield "busy", None

    def _approval(self, data: dict) -> str:
        """Records the approval as pending, waits for your «yes» in the background, returns the question."""
        run_id = data.get("run_id", "")
        action = data.get("description") or data.get("reason") or data.get("command") or "?"
        log.info("Hermes asks for approval (%s): %s", run_id, settings.private(action))
        confirmation = kernel.module("confirmation")
        if confirmation is None:  # turned off: nothing asks
            asyncio.ensure_future(self._approve(run_id, "once"))
            return ""
        # «consume»: the «yes» or «no» is for Hermes, not a new message to it.
        confirmation.store.ask(run_id, action, consume=True)
        asyncio.ensure_future(self._await_answer(run_id))
        return " " + i18n.L("speech.hermes_approval", action=action)

    async def _await_answer(self, run_id: str):
        """Your answer, through the plugin «confirmation» (the same «yes» as everything else)."""
        store = kernel.module("confirmation").store
        deadline = time.time() + (settings.get("confirm_wait") or store.WAIT)  # then it is denied
        choice = "deny"
        while time.time() < deadline:
            await asyncio.sleep(0.2)
            if store.confirmed(run_id):
                choice = "once"
                break
            if not store.waiting(run_id):
                break  # the answer wasn't «yes»
        await self._approve(run_id, choice)

    async def _approve(self, run_id: str, choice: str):
        log.info("Hermes approval (%s): %s", run_id, choice)
        http = await self._client()
        async with http.post(f"{HERMES}/v1/runs/{run_id}/approval", json={"choice": choice}) as r:
            if r.status != 200:
                log.warning("Hermes rejected the approval: %s %s", r.status, (await r.text())[:200])
