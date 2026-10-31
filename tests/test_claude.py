"""The Claude plugin keeps a spare process ready, and drops it when it is out of date."""

import asyncio

import pytest

from llm import claude


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
