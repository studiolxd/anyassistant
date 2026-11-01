"""The plugin «interpreter»: only sentences that may be a skill go to its model."""

import asyncio

import kernel

kernel.load_all()
interpreter = kernel.load("interpreter")


def test_a_sentence_that_isnt_a_skill_isnt_interpreted(monkeypatch):
    monkeypatch.setattr(interpreter, "enabled", lambda: True)
    monkeypatch.setattr(interpreter, "sounds_like_one", lambda text: False)
    assert asyncio.run(interpreter.interpret("¿qué tiempo hace?")) is None  # it used to raise
