"""Brains: what Jarvis does with what it hears (settings «mode»), each a plugin of kind
«brain» that registers itself:

    @register("assistant")
    class Assistant: ...
        @classmethod
        def create(cls, args): …   # → brain(speaker, send), one per connected device

assistant (the voice assistant: plugins/brain-assistant), transcribe (only shows what
it hears: brain-transcriber, whose Ear the assistant uses too) and parrot (repeats it:
brain-parrot). Each builds the engines it needs (STT, wake word, LLM, voice) from the
settings.
"""

from registry import Registry

_registry = Registry("brain", "brain")
register = _registry.register
available = _registry.available
get = _registry.get


def create(name: str, args):
    """The chosen brain's factory: brain(speaker, send) → the object a Session talks to."""
    found = get(name)
    if not found:
        raise ValueError(f"Unknown brain: {name}. Available: {', '.join(available())}")
    return found.create(args)
