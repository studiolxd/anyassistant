"""Apple's model that comes with macOS (Foundation Models, ~3B, local).

Talks to apple_bridge.swift, built the first time into .build/.
Requires macOS 26+ with Apple Intelligence enabled.
"""

import asyncio
import json
import logging
import subprocess
from pathlib import Path

import i18n
from llm import LLM, instructions, register
from swift import build

log = logging.getLogger("llm")

# Given the time in the prompt, it repeats it in every answer: it goes as a tool.
DATE_TIME_TOOL = "\nIf asked for the date or the time, look them up with the dateTime tool."


@register("apple")
class Apple(LLM):
    def __init__(self, model=None, mcp=None):
        super().__init__(model or "SystemLanguageModel.default", mcp)
        self._binary = build(Path(__file__).with_name("apple_bridge.swift"), "fm-bridge")
        self._process = None
        self._turn = asyncio.Lock()  # the bridge handles one command at a time

    async def _start(self):
        if self._process and self._process.returncode is None:
            return
        self._process = await asyncio.create_subprocess_exec(
            str(self._binary), stdin=subprocess.PIPE, stdout=subprocess.PIPE
        )
        ready = await self._read()
        if "error" in ready:
            raise RuntimeError(f"Apple model: {ready['error']}")

    async def _read(self) -> dict:
        return json.loads(await self._process.stdout.readline())

    async def _send(self, command: dict):
        self._process.stdin.write(json.dumps(command).encode() + b"\n")
        await self._process.stdin.drain()

    async def close(self):
        if self._process and self._process.returncode is None:
            self._process.kill()
            await self._process.wait()

    async def new(self):
        async with self._turn:
            await self._start()
            await self._send({"type": "new", "instructions": instructions() + DATE_TIME_TOOL})
            await self._read()

    # Its context is ~4,000 tokens: the memory review only gets the end of a long conversation.
    context_chars = 6000

    async def complete(self, prompt: str) -> str:
        """One answer outside the conversation, in a session of its own (the next «new» replaces it)."""
        async with self._turn:
            await self._start()
            await self._send({"type": "new", "instructions": "Do exactly what is asked. Answer only with what is asked."})
            await self._read()
            await self._send({"type": "ask", "text": prompt, "now": i18n.L.now_spoken()})
            text = ""
            while True:
                message = await self._read()
                if "delta" in message:
                    text += message["delta"]
                elif "error" in message:
                    raise RuntimeError(message["error"])
                else:
                    return text

    async def prepare(self):
        """After a review, its session is the review's: a new conversation for the next one."""
        await self.new()

    async def answer(self, text: str, image: bytes | None = None):  # it can't see: no image
        async with self._turn:
            await self._start()
            await self._send({"type": "ask", "text": text, "now": i18n.L.now_spoken()})
            while True:
                message = await self._read()
                if "delta" in message:
                    yield message["delta"]
                elif "error" in message:
                    log.warning("model error: %s", message["error"])
                    key = "speech.guardrail" if message["error"] == "guardrail" else "speech.llm_failed"
                    yield i18n.L(key)
                    return
                else:
                    return
