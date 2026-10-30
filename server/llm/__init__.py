"""LLM plugins (text → streamed answer).

A plugin is a module of this package with a class registered like this:

    @register("name")
    class MyLLM(LLM):
        async def new(self): ...                # starts a conversation (forgets the last one)
        async def answer(self, text):           # async generator of text pieces
            yield "Hello"
        async def close(self): ...              # optional, when the server stops
"""

from collections.abc import AsyncIterator

import i18n
from plugins import Registry

_registry = Registry(__name__, __path__, "LLM")
register = _registry.register
create = _registry.create
available = _registry.available

INSTRUCTIONS = """You are Jarvis, a voice assistant. Always reply in {language}.
What you receive is what the user said out loud, transcribed automatically: it
may contain mistakes; interpret it with common sense.
Your answer will be read aloud: be brief (one to three sentences), natural and
direct. No lists, markdown, emojis or symbols. If you don't know something, say so.
Don't assume the user's gender: use neutral forms."""


def instructions() -> str:
    """The system instructions, in the active language."""
    return INSTRUCTIONS.format(language=i18n.L.name)


class LLM:
    name = "?"

    def __init__(self, model: str | None = None, mcp: str | None = None):
        self.model = model
        self.mcp = mcp  # path to .mcp.json; only plugins that support MCP use it

    async def new(self):
        raise NotImplementedError

    def answer(self, text: str) -> AsyncIterator[str]:
        raise NotImplementedError

    async def reload(self):
        """Reads its configuration again (permissions, tools) and starts over."""
        await self.new()

    async def close(self):
        """When the server stops: releases processes or connections."""
