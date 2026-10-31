"""Events: what happens, for whichever plugins care.

    @events.on("asleep")
    def review(jarvis, transcript): ...        # a plugin listens (sync or async)

    events.emit("asleep", jarvis, transcript)  # the core says it happened

Only the handlers of plugins that are on are called; one failing doesn't stop the
others. Events so far: «tap» (jarvis): the screen was tapped; «asleep» (jarvis, transcript):
it fell asleep after a conversation (awaited with gather: memory reviews it before
the next one is prepared).
"""

import asyncio
import inspect
import logging

import kernel

log = logging.getLogger("events")
_handlers: dict[str, list] = {}


def on(name: str):
    def register(function):
        plugin = kernel.current()
        handlers = _handlers.setdefault(name, [])  # loaded again: replaces itself
        handlers[:] = [h for h in handlers if (h[0].__qualname__, h[1]) != (function.__qualname__, plugin)]
        handlers.append((function, plugin))
        return function
    return register


def emit(name: str, *args, **kwargs):
    """Calls its handlers; coroutines run in the background."""
    kernel.load_all()
    for function, plugin in list(_handlers.get(name, [])):
        if not kernel.enabled(plugin):
            continue
        try:
            result = function(*args, **kwargs)
            if inspect.isawaitable(result):
                asyncio.ensure_future(result)
        except Exception as e:
            log.warning("%s (%s): %r", name, plugin, e)


async def gather(name: str, *args, **kwargs):
    """Like emit, but waits for every handler (sync or async) to finish."""
    kernel.load_all()
    for function, plugin in list(_handlers.get(name, [])):
        if not kernel.enabled(plugin):
            continue
        try:
            result = function(*args, **kwargs)
            if inspect.isawaitable(result):
                await result
        except Exception as e:
            log.warning("%s (%s): %r", name, plugin, e)
