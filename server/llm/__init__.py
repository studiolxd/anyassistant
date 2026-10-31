"""LLM plugins (text → streamed answer).

A plugin is a module of this package with a class registered like this:

    @register("name")
    class MyLLM(LLM):
        async def new(self): ...                # starts a conversation (forgets the last one)
        async def answer(self, text, image=None):  # async generator of text pieces;
            yield "Hello"                       # image: JPEG from the camera, if it can see
        async def complete(self, prompt): ...   # optional: one answer, outside the conversation
        async def prepare(self): ...            # optional: get ready for the next conversation
        async def close(self): ...              # optional, when the server stops
"""

from collections.abc import AsyncIterator

import i18n
import memory
import settings
from plugins import Registry

_registry = Registry(__name__, __path__, "LLM")
register = _registry.register
create = _registry.create
available = _registry.available

INSTRUCTIONS = """You are {name}, a voice assistant. Always reply in {language}.
What you receive is what the user said out loud, transcribed automatically: it
may contain mistakes; interpret it with common sense.
Your answer will be read aloud: natural and direct, no lists, markdown, emojis
or symbols. {detail} If you don't know something, say so.
Don't assume the user's gender: use neutral forms."""

# How much to say (settings «detail»); «detail_levels» in settings.json adds levels
# or changes these: {"name": "the instruction added to the prompt"}.
DETAIL_LEVELS = {
    "concise": "Answer in one short sentence with only the essential: no pleasantries and no "
               "follow-up questions unless you need something to go on.",
    "neutral": "Be brief: one to three sentences.",
    "detailed": "Give a complete answer with the relevant details and context, up to a short "
                "paragraph or two; it is still spoken, so no lists.",
}


def detail_levels() -> dict[str, str]:
    return {**DETAIL_LEVELS, **(settings.get("detail_levels") or {})}


def detail() -> str:
    """The instruction of the current detail level (neutral's if it is unknown)."""
    levels = detail_levels()
    return levels.get(settings.get("detail") or "neutral", levels["neutral"])


def instructions() -> str:
    """The system instructions, in the active language, plus the user's own (settings «instructions»)."""
    text = INSTRUCTIONS.format(language=i18n.L.name, name=settings.get("name", "Jarvis"), detail=detail())
    extra = settings.get("instructions")
    if extra:
        text += f"\n\nFrom the user:\n{extra}"
    return text + memory.instructions()


class LLM:
    name = "?"

    def __init__(self, model: str | None = None, mcp: str | None = None):
        self.model = model
        self.mcp = mcp  # path to .mcp.json; only plugins that support MCP use it
        self.on_tool = lambda name: None  # called when the model uses a tool (the face shows it)

    async def new(self):
        raise NotImplementedError

    def answer(self, text: str, image: bytes | None = None) -> AsyncIterator[str]:
        raise NotImplementedError

    async def complete(self, prompt: str) -> str:
        """One answer outside the conversation (to review it for memory)."""
        raise NotImplementedError

    async def prepare(self):
        """Gets ready for the next conversation (e.g. after the memory changed)."""

    async def reload(self):
        """Reads its configuration again (permissions, tools) and starts over."""
        await self.new()

    async def close(self):
        """When the server stops: releases processes or connections."""
