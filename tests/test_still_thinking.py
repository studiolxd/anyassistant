"""A filler said («Un momento, lo miro») while the answer still comes: the face thinks again
when it ends, instead of a speaking mouth standing still."""

import asyncio

import kernel

assistant = kernel.load("brain-assistant")


class Speaker:
    speaking = False


class Lock:
    def __init__(self, held):
        self.held = held

    def locked(self):
        return self.held


class Brain:
    _still_thinking = assistant.Assistant._still_thinking

    def __init__(self, answering=True, waiting=False, shown="speaking"):
        self.speaker, self.turn, self.shown = Speaker(), Lock(answering), shown
        self.sentences = asyncio.Queue()
        if waiting:
            self.sentences.put_nowait((1, "más"))
        self.number, self.cut, self.states = 1, None, []

    def _state(self, state):
        self.states.append(state)


def test_back_to_thinking_while_the_answer_still_comes():
    brain = Brain()
    asyncio.run(brain._still_thinking(1))
    assert brain.states == ["thinking"]


def test_not_when_more_is_ready_the_answer_ended_or_it_shows_something_else():
    for brain in (Brain(waiting=True), Brain(answering=False), Brain(shown="looking")):
        asyncio.run(brain._still_thinking(1))
        assert brain.states == []
