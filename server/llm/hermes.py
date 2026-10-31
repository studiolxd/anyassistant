"""Hermes Agent as the LLM, through its OpenAI-compatible API (`hermes gateway`).

Hermes uses its own tools, memory and credentials: whatever it already has set up
doesn't need to be granted again. permissions.json doesn't apply to it; what is
kept is the voice confirmation: when Hermes asks to approve an action (SSE event
`approval.request`), Jarvis asks you and answers Hermes with `once` if you say
«yes» or `deny` otherwise (POST /v1/runs/{id}/approval).

The key comes from API_SERVER_KEY in ~/.hermes/.env (or HERMES_API_KEY), and the
address from HERMES_API_URL (default http://127.0.0.1:8642).
Each conversation is a Hermes session (X-Hermes-Session-Id header).
"""

import asyncio
import base64
import json
import logging
import os
import time
import uuid
from pathlib import Path

import confirmation
import i18n
import settings
from llm import LLM, instructions, register

log = logging.getLogger("llm")

URL = os.environ.get("HERMES_API_URL", "http://127.0.0.1:8642")
ENV = Path.home() / ".hermes" / ".env"
# Same files as Claude's confirmation (bin/jarvis-confirm, brain/assistant.py).


def api_key() -> str:
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
class Hermes(LLM):
    spoken = ["hermes"]

    @classmethod
    def ready(cls):
        import urllib.request

        try:
            urllib.request.urlopen(URL + "/health", timeout=1)
            return None
        except OSError:
            return "Hermes's gateway isn't running"

    def __init__(self, model=None, mcp=None):
        super().__init__(model or "hermes-agent", mcp)
        self._key = api_key()
        self._http = None
        self._session = None
        self._turn = asyncio.Lock()

    async def _client(self):
        import aiohttp

        if self._http is None or self._http.closed:
            self._http = aiohttp.ClientSession(
                base_url=URL, headers={"Authorization": f"Bearer {self._key}"},
                timeout=aiohttp.ClientTimeout(total=None, sock_connect=5),
            )
        return self._http

    async def new(self):
        self._session = f"jarvis-{uuid.uuid4().hex[:12]}"

    async def close(self):
        if self._http and not self._http.closed:
            await self._http.close()

    async def answer(self, text: str, image: bytes | None = None):
        import aiohttp

        async with self._turn:
            if not self._session:
                await self.new()
            http = await self._client()
            body = {
                "model": self.model, "stream": True,
                "messages": [{"role": "system", "content": instructions()},
                             {"role": "user", "content": self._content(text, image)}],
            }
            said = False
            try:
                async with http.post("/v1/chat/completions", json=body,
                                     headers={"X-Hermes-Session-Id": self._session}) as r:
                    if r.status != 200:
                        log.warning("Hermes answered %s: %s", r.status, (await r.text())[:300])
                        yield i18n.L("speech.llm_failed")
                        return
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
                        if event == "approval.request":
                            said = True
                            yield self._approval(data)
                        elif event == "hermes.tool.progress":
                            log.info("Hermes tool: %s", data.get("tool") or data.get("name"))
                            if not said and settings.get("fillers", True):
                                said = True
                                yield i18n.L("speech.wait") + " "
                        elif event is None:
                            delta = (data.get("choices") or [{}])[0].get("delta", {}).get("content")
                            if delta:
                                said = True
                                yield delta
                        event = None
            except aiohttp.ClientConnectorError:
                yield i18n.L("speech.hermes_down")

    @staticmethod
    def _content(text: str, image: bytes | None):
        """The message, with the camera's image if it looked (OpenAI's format, which Hermes takes)."""
        if not image:
            return text
        url = "data:image/jpeg;base64," + base64.b64encode(image).decode()
        return [{"type": "text", "text": text}, {"type": "image_url", "image_url": {"url": url}}]

    def _approval(self, data: dict) -> str:
        """Records the approval as pending, waits for your «yes» in the background, returns the question."""
        run_id = data.get("run_id", "")
        action = data.get("description") or data.get("reason") or data.get("command") or "?"
        log.info("Hermes asks for approval (%s): %s", run_id, settings.private(action))
        # «consume»: the «yes» or «no» is for Hermes, not a new message to it.
        confirmation.ask(run_id, action, consume=True)
        asyncio.ensure_future(self._await_answer(run_id))
        return " " + i18n.L("speech.hermes_approval", action=action)

    async def _await_answer(self, run_id: str):
        deadline = time.time() + settings.get("confirm_wait", confirmation.WAIT)  # then it is denied
        choice = "deny"
        while time.time() < deadline:
            await asyncio.sleep(0.2)
            if confirmation.confirmed(run_id):
                choice = "once"
                break
            if not confirmation.waiting(run_id):
                break  # the answer wasn't «yes»
        log.info("Hermes approval (%s): %s", run_id, choice)
        http = await self._client()
        async with http.post(f"/v1/runs/{run_id}/approval", json={"choice": choice}) as r:
            if r.status != 200:
                log.warning("Hermes rejected the approval: %s %s", r.status, (await r.text())[:200])
