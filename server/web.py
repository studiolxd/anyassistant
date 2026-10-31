"""The server's web side: the page, its configuration and skins, WebRTC signaling,
the hooks plugins use (routes, guards like pairing's, /config, startup tasks). main.py chooses the brain and runs it."""

import asyncio
import logging
import uuid
from html import escape

from aiohttp import web

import hub
import i18n
import settings
from brain.parrot import Parrot
import kernel
from transport import Session

brain = Parrot  # what each connection talks to; main.py chooses it (--mode)
close_on_exit = []  # coroutines to await when stopping (plugin processes)


# --- What plugins hook into ---

ROUTES = []  # (method, path, handler, plugin)
GUARDS = []  # (function, plugin): may refuse a request to a protected route
CONFIG = []  # (function, plugin): more for the page's /config
STARTUP = []  # (function, plugin): async function(app), when the server starts (a background loop…)


def _put(hooks: list, entry: tuple, same) -> None:
    """Adds a hook; one the same plugin registered before (loaded again) is replaced."""
    hooks[:] = [h for h in hooks if not same(h)] + [entry]


def route(method: str, path: str):
    """A plugin's own HTTP route (off with its plugin)."""
    def register(handler):
        _put(ROUTES, (method, path, handler, kernel.current()), lambda h: h[:2] == (method, path))
        return handler
    return register


def _hook(hooks: list):
    def register(function):
        plugin = kernel.current()
        _put(hooks, (function, plugin), lambda h: (h[0].__qualname__, h[1]) == (function.__qualname__, plugin))
        return function
    return register


guard = _hook(GUARDS)
guard.__doc__ = "function(request) → a refusal (web.Response) or None; for every protected route."
config = _hook(CONFIG)
config.__doc__ = "function(request) → a dict added to /config, for the page."
startup = _hook(STARTUP)
startup.__doc__ = "async function(app) when the server starts; a loop it starts should check its plugin is on."


def refused(request: web.Request) -> web.Response | None:
    """A plugin's refusal of this request (pairing…), or None."""
    for function, plugin in GUARDS:
        if kernel.enabled(plugin):
            answer = function(request)
            if answer is not None:
                return answer
    return None


def is_allowed(request: web.Request) -> bool:
    return refused(request) is None


async def offer(request: web.Request) -> web.Response:
    if refusal := refused(request):
        return refusal
    data = await request.json()
    session = Session(uuid.uuid4().hex[:6], brain)
    # A single phone: the new connection replaces the previous ones.
    for old in list(hub.sessions.values()):
        await old.close()
    hub.sessions.clear()
    hub.sessions[session.id] = session
    answer = await session.answer(data["sdp"], data["type"])
    return web.json_response({"sdp": answer.sdp, "type": answer.type})


async def status(request: web.Request) -> web.Response:
    if refusal := refused(request):
        return refusal
    session = hub.current()
    return web.json_response({
        "connected": bool(session and session.pc.connectionState == "connected"),
        "frames": session.frames if session else 0,
    })


def contributed(request: web.Request) -> dict:
    """What the plugins add to the page's /config (@web.config)."""
    more = {}
    for function, plugin in CONFIG:
        if kernel.enabled(plugin):
            more.update(function(request))
    return more


def page(file) -> web.Response:
    """A plugin's HTML page (a Path), declaring the active language (lang="…") and the name from the start."""
    html = file.read_text().replace('<html lang="en"', f'<html lang="{i18n.L.code}"', 1)
    html = html.replace("<title>Jarvis", f"<title>{escape(settings.get('name', 'Jarvis'))}", 1)
    return web.Response(text=html, content_type="text/html")


@web.middleware
async def no_cache(request: web.Request, handler):
    # Prototype: the phone always gets the latest version of the page.
    # And no keep-alive: after a server restart, Chrome 81 got stuck reusing a
    # dead connection instead of opening a new one.
    response = await handler(request)
    response.headers["Cache-Control"] = "no-store"
    if request.path in ("/", "/lab"):
        # Skins are someone else's HTML and CSS on a page with the microphone and the camera:
        # nothing from outside, and no scripts but Jarvis's own.
        response.headers["Content-Security-Policy"] = (
            "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; "
            "img-src 'self' blob: data:; media-src 'self' blob: mediastream:; font-src 'self'; "
            "connect-src 'self'; frame-src 'self'; object-src 'none'; base-uri 'none'; form-action 'self'")
    response.force_close()
    return response


async def on_shutdown(app: web.Application):
    # With a time limit: if something hangs while closing, the process must not stay
    # alive (and «restart» would never come back).
    steps = [s.close() for s in hub.sessions.values()] + [close() for close in close_on_exit]
    for step in steps:
        try:
            await asyncio.wait_for(step, 5)
        except Exception as e:
            logging.warning("while closing: %r", e)


def _while_on(handler, plugin):
    async def guarded(request):
        if not kernel.enabled(plugin):  # turned off since: as if it weren't there
            raise web.HTTPNotFound()
        return await handler(request)
    return guarded


def application() -> web.Application:
    app = web.Application(middlewares=[no_cache], client_max_size=20 * 1024 * 1024)  # photos
    app.router.add_post("/offer", offer)
    app.router.add_get("/status", status)
    kernel.load_all()
    for method, path, handler, plugin in ROUTES:  # the plugins' own
        app.router.add_route(method, path, _while_on(handler, plugin))
    app.on_shutdown.append(on_shutdown)
    for function, plugin in STARTUP:  # the plugins' background tasks (they check they're on)
        app.on_startup.append(function)
    return app
