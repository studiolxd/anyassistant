"""The Claude plugin keeps a spare process ready, and drops it when it is out of date."""

import asyncio
import json

import pytest

import plugins.llm_claude as claude


class Process:
    returncode = None

    def __init__(self, n):
        self.n = n


@pytest.fixture
def model(monkeypatch, en):
    spawned = []

    async def spawn(self):
        spawned.append(Process(len(spawned)))
        return spawned[-1]

    async def kill(process):
        if process:
            process.returncode = 0

    monkeypatch.setattr(claude.Claude, "_spawn", spawn)
    monkeypatch.setattr(claude.Claude, "_kill", staticmethod(kill))
    model = object.__new__(claude.Claude)
    model.model, model._instructions, model._process, model._spare = "sonnet", "A", None, None
    model._permissions = type("P", (), {"arguments": []})()
    return model, spawned


def test_uses_the_spare_and_prepares_another(model):
    model, spawned = model
    asyncio.run(model._start())
    assert model._process.n == 0 and model._spare.n == 1
    asyncio.run(model._start())
    assert model._process.n == 1 and model._spare.n == 2  # no waiting: the spare


def test_a_stale_spare_is_dropped(model):
    model, spawned = model
    asyncio.run(model._start())
    model._instructions = "B"  # e.g. «remember that…» changed the instructions
    asyncio.run(model._start())
    assert spawned[1].returncode == 0  # the old spare, closed
    assert model._process.n == 2 and model._spare.n == 3


class Stdout:
    """Claude's stream-json output, each line after its delay."""

    def __init__(self, lines):
        self.lines = list(lines)

    async def readline(self):
        if not self.lines:
            return b""
        delay, event = self.lines.pop(0)
        await asyncio.sleep(delay)
        return (json.dumps(event) + "\n").encode()


def tool_use(name):
    return {"type": "stream_event", "event": {"content_block": {"type": "tool_use", "name": name}}}


def text(t):
    return {"type": "stream_event", "event": {"delta": {"type": "text_delta", "text": t}}}


TOOL_RESULT = {"type": "user", "message": {"content": [{"type": "tool_result"}]}}
END = {"type": "result"}


def answer(monkeypatch, lines):
    monkeypatch.setattr(claude, "FILLER_AFTER", 0.2)
    model = object.__new__(claude.Claude)
    model._turn, model.on_tool = asyncio.Lock(), lambda name, arguments=None: None
    stdin = type("Stdin", (), {"write": lambda self, b: None, "drain": lambda self: asyncio.sleep(0)})()
    model._process = type("Process", (), {"returncode": None, "stdin": stdin, "stdout": Stdout(lines)})()

    async def collect():
        return [piece async for piece in model.answer("hi")]
    return "".join(asyncio.run(collect()))


def test_a_slow_tool_gets_a_filler(monkeypatch, es):
    said = answer(monkeypatch, [(0, tool_use("mcp__holded__list_invoices")), (0.5, TOOL_RESULT), (0, text("Tienes 3.")), (0, END)])
    assert any(said.startswith(w) for w in es.list("speech.wait")) and said.endswith("Tienes 3.")


def test_a_quick_tool_or_a_confirmation_does_not(monkeypatch, es):
    said = answer(monkeypatch, [(0, tool_use("mcp__anyassistant__set_theme")), (0.05, TOOL_RESULT),
                                (0.4, text("¿Cambio la cara?")), (0, END)])
    assert said == "¿Cambio la cara?"


def test_tools_are_reported_with_their_arguments(monkeypatch, es):
    """Reading the camera's image is looking; reading a saved tool result (invoices) isn't."""
    seen = []
    monkeypatch.setattr(claude, "FILLER_AFTER", 5)
    model = object.__new__(claude.Claude)
    model._turn, model.on_tool = asyncio.Lock(), lambda name, arguments=None: seen.append((name, arguments))
    whole = {"type": "assistant", "message": {"content": [
        {"type": "tool_use", "name": "Read", "input": {"file_path": "/tmp/tool-results/invoices.txt"}}]}}
    lines = [(0, tool_use("Read")), (0, whole), (0, TOOL_RESULT), (0, text("Unos 46.000.")), (0, END)]
    stdin = type("Stdin", (), {"write": lambda self, b: None, "drain": lambda self: asyncio.sleep(0)})()
    model._process = type("Process", (), {"returncode": None, "stdin": stdin, "stdout": Stdout(lines)})()

    async def collect():
        return [piece async for piece in model.answer("hi")]
    asyncio.run(collect())
    assert seen == [("Read", None), ("Read", {"file_path": "/tmp/tool-results/invoices.txt"})]
