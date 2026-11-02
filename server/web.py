"""The server's web side: the page, its configuration and themes, WebRTC signaling,
the hooks plugins use (routes, guards like pairing's, /config, startup tasks). main.py chooses the brain and runs it."""

import asyncio
import logging
import re
import uuid

from aiohttp import web

import events
import hub
import i18n
import kernel
import paths
import settings
from transport import Session

brain = None  # brain(speaker, send): what each connection talks to; main.py chooses it (--mode)
close_on_exit = []  # coroutines to await when stopping (plugin processes)
restarting = False  # stop() asked to start again (main.py does it)


def stop(restart: bool = False):
    """Stops the server cleanly (sessions, plugins), as Ctrl+C; with restart, it starts again.
    From the event loop: the same on macOS, Linux and Windows (no signals)."""
    global restarting
    restarting = restarting or restart

    def leave():
        raise web.GracefulExit()  # a SystemExit: it gets out of the loop, then run_app closes everything

    asyncio.get_running_loop().call_soon(leave)


# --- What plugins hook into ---

ROUTES = []  # (method, path, handler, plugin)
GUARDS = []  # (function, plugin): may refuse a request to a protected route
CONFIG = []  # (function, plugin): more for the page's /config
STARTUP = []  # (function, plugin): async function(app), when the server starts (a background loop…)
OWNERS = []  # (function, plugin): function(request) → True if it comes from the owner (an admin's browser)
LOCAL = {"127.0.0.1", "::1"}


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
owner_check = _hook(OWNERS)
owner_check.__doc__ = "function(request) → True if the request comes from the owner (the plugin «admin»: its code)."


def owner(request: web.Request) -> bool:
    """Whether a request may administer: from this computer itself, or a browser given an admin code."""
    if request.remote in LOCAL:
        return True
    return any(function(request) for function, plugin in OWNERS if kernel.enabled(plugin))


def only_the_owner(handler):
    """A route only the owner may use (settings, plugins, devices, voices, mail, pairing codes)."""
    async def checked(request):
        if not owner(request):
            return web.json_response({"owner": False}, status=403)
        return await handler(request)
    checked.__name__ = handler.__name__
    return checked


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
    device = str(data.get("device") or "")  # the page's own id (several devices at once): a name in files too
    device = device if re.fullmatch(r"[A-Za-z0-9_-]{1,64}", device) else None
    session = Session(uuid.uuid4().hex[:6], brain, device)
    session.agent = request.headers.get("User-Agent", "")
    session.remote = request.remote or ""  # 127.0.0.1: the computer's own app (microphone-busy)
    for old in hub.add(session):  # the same device connecting again: its old connection goes
        await old.close()
    events.emit("connected", session)  # its name and room (the plugin «devices»)…
    answer = await session.answer(data["sdp"], data["type"])
    return web.json_response({"sdp": answer.sdp, "type": answer.type})


def identity() -> str:
    """This server's own id, made once and kept (server-id): how a paired app tells it from another
    server on the same network when it looks for it by Bonjour (its IP changed)."""
    file = paths.HOME / "server-id"
    try:
        return file.read_text().strip()
    except OSError:
        made = uuid.uuid4().hex[:12]
        try:
            file.write_text(made)
        except OSError:
            pass
        return made


async def status(request: web.Request) -> web.Response:
    if refusal := refused(request):
        return refusal
    session = hub.current()
    connected = [s for s in hub.all() if s.pc.connectionState == "connected"]
    devices = kernel.module("devices")  # their names and rooms, if it's on
    return web.json_response({
        "server": identity(),  # which one it is (also in its Bonjour announcement)
        "connected": bool(connected),
        "frames": session.frames if session else 0,
        "llm": settings.get("llm"),
        "devices": [_device(s, s is session, devices) for s in connected],
    })


def _device(session, current: bool, devices) -> dict:
    """A connected device, for the apps' menus: its name, room, kind (its icon) and LLM."""
    known = devices.load().get(session.device or "", {}) if devices else {}
    own = devices.llm_of(session.device) if devices else None
    ear = getattr(session.brain, "ear", None)
    why, app = ear.pause_reason if ear is not None and getattr(ear, "paused", None) else ("", "")
    return {"id": session.device or session.id, "name": known.get("name", ""), "room": known.get("room", ""),
            "kind": devices.kind(known.get("agent") or getattr(session, "agent", "")) if devices else "",
            "llm": own or settings.get("llm"), "own_llm": bool(own), "current": current,
            "local": getattr(session, "remote", "") in LOCAL,  # the computer's own app (its tray says if paused)
            "paused": {"why": why, "app": app} if why else None}


# --- The installer's «device» steps (installer.device), once the server runs: the app's window ---

def own_device():
    """This computer's own device (its app's face, connected from 127.0.0.1): where a «device» step
    is done; the last one connected if there are several."""
    found = [s for s in hub.all() if getattr(s, "remote", "") in LOCAL and s.device
             and s.pc.connectionState == "connected" and hasattr(s.brain, "say")]
    return found[-1] if found else None


async def setup_device(request: web.Request) -> web.Response:
    """GET: {"device": this computer's device (None: not connected yet), "state": where the step is};
    POST {"do": "start"|"cancel"}: starts it there, or stops it. Only from this computer (or an admin)."""
    import installer

    if not owner(request):
        return web.json_response({"owner": False}, status=403)
    step = installer.device_step(request.match_info["step"])
    if step is None:
        return web.json_response({"error": "no such step here (its plugin is off?)"}, status=404)
    session = own_device()
    if request.method == "POST":
        data = await request.json()
        if session is None:
            return web.json_response({"error": "no device on this computer is connected"}, status=409)
        if data.get("do") == "start":
            token = hub.here.set(session)
            try:
                step.function(session)
            finally:
                hub.here.reset(token)
        elif data.get("do") == "cancel" and step.cancel:
            step.cancel(session.device)
    device = session.device if session else None
    state = step.follow(device) if device and step.follow else None
    return web.json_response({"device": device, "state": state})


def contributed(request: web.Request) -> dict:
    """What the plugins add to the page's /config (@web.config)."""
    more = {}
    for function, plugin in CONFIG:
        if kernel.enabled(plugin):
            more.update(function(request))
    return more


def page(file) -> web.Response:
    """A plugin's HTML page (a Path), declaring the active language (lang="…") from the start."""
    html = file.read_text().replace('<html lang="en"', f'<html lang="{i18n.L.code}"', 1)
    return web.Response(text=html, content_type="text/html")


@web.middleware
async def no_cache(request: web.Request, handler):
    # Prototype: the phone always gets the latest version of the page.
    # And no keep-alive: after a server restart, Chrome 81 got stuck reusing a
    # dead connection instead of opening a new one.
    response = await handler(request)
    response.headers["Cache-Control"] = "no-store"
    if request.path in ("/", "/themes"):
        # Themes are someone else's HTML and CSS on a page with the microphone and the camera:
        # nothing from outside, and no scripts but Jarvis's own. Media from data: (NoSleep.js
        # carries its silent video so: it keeps the screen on), still nothing from outside.
        response.headers["Content-Security-Policy"] = (
            "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; "
            "img-src 'self' blob: data:; media-src 'self' blob: data: mediastream:; font-src 'self'; "
            "connect-src 'self'; frame-src 'self'; object-src 'none'; base-uri 'none'; form-action 'self'")
    response.force_close()
    return response


async def on_shutdown(app: web.Application):
    # With a time limit: if something hangs while closing, the process must not stay
    # alive (and «restart» would never come back).
    steps = [s.close() for s in hub.all()] + [close() for close in close_on_exit]
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
    app.router.add_get("/setup/device/{step}", setup_device)  # the installer's «device» steps
    app.router.add_post("/setup/device/{step}", setup_device)
    kernel.load_all()
    for method, path, handler, plugin in ROUTES:  # the plugins' own
        app.router.add_route(method, path, _while_on(handler, plugin))
    app.on_shutdown.append(on_shutdown)
    for function, plugin in STARTUP:  # the plugins' background tasks (they check they're on)
        app.on_startup.append(function)
    return app
