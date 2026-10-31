"""The server's web side: the page, its configuration and skins, WebRTC signaling,
the hooks plugins use (routes, guards like pairing's, /config), the camera monitor, its MCP server, and the loop that
rings alarms. main.py chooses the brain and runs it."""

import asyncio
import logging
import uuid
from html import escape

from aiohttp import web

import hub
import i18n
import mcp_server
import paths
import settings
import skins
from brain.parrot import Parrot
import kernel
from skills import timers as skill_timers
from transport import Session

WEB = paths.WEB
brain = Parrot  # what each connection talks to; main.py chooses it (--mode)
close_on_exit = []  # coroutines to await when stopping (plugin processes)


# --- What plugins hook into ---

ROUTES = []  # (method, path, handler, plugin)
GUARDS = []  # (function, plugin): may refuse a request to a protected route
CONFIG = []  # (function, plugin): more for the page's /config


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


async def video_mjpeg(request: web.Request) -> web.StreamResponse:
    """What the camera sees, to watch it from the Mac's browser."""
    if refusal := refused(request):
        return refusal
    response = web.StreamResponse(headers={"Content-Type": "multipart/x-mixed-replace; boundary=frame"})
    await response.prepare(request)
    while True:
        session = hub.current()
        image = session.jpeg() if session else None
        if image:
            await response.write(b"--frame\r\nContent-Type: image/jpeg\r\n\r\n" + image + b"\r\n")
        await asyncio.sleep(1 / 10)


async def status(request: web.Request) -> web.Response:
    if refusal := refused(request):
        return refusal
    session = hub.current()
    return web.json_response({
        "connected": bool(session and session.pc.connectionState == "connected"),
        "frames": session.frames if session else 0,
    })


async def skin_file(request: web.Request) -> web.StreamResponse:
    """A skin's stylesheet, images, fonts or sounds: only from inside its folder."""
    path = skins.asset(request.match_info["name"], request.match_info["path"])
    return web.FileResponse(path) if path else web.Response(status=404)


async def lab(request: web.Request) -> web.Response:
    """The skins lab: every state of a skin at once, reloading when its files change."""
    return page("lab.html")


async def page_config(request: web.Request) -> web.Response:
    """What the page needs: its texts in the active language (locale «ui»), the settings and the skin
    (?skin=: this device's own)."""
    chosen = request.query.get("skin", "")
    return web.json_response({
        "lang": i18n.L.code, "ui": i18n.L.data["ui"],
        "name": settings.get("name"), "video": settings.get("video"),
        "skin": skins.for_page(chosen if chosen in skins.available() else settings.get("skin"), i18n.L.code),
        "skins": [{"name": name, "title": skins.manifest(name).get("name", name),
                   "description": skins.manifest(name).get("description", "")} for name in skins.available()],
        "screen": {key: settings.get(key) for key in settings.SCREEN},
        **_contributed(request),
    })


def _contributed(request: web.Request) -> dict:
    more = {}
    for function, plugin in CONFIG:
        if kernel.enabled(plugin):
            more.update(function(request))
    return more


def page(name: str) -> web.Response:
    """An HTML page declaring the active language (lang="…") and the name from the start."""
    html = (WEB / name).read_text().replace('<html lang="en"', f'<html lang="{i18n.L.code}"', 1)
    html = html.replace("<title>Jarvis", f"<title>{escape(settings.get('name', 'Jarvis'))}", 1)
    return web.Response(text=html, content_type="text/html")


async def index(request: web.Request) -> web.Response:
    return page("index.html")


async def monitor(request: web.Request) -> web.Response:
    return page("monitor.html")


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


async def ring_when_due(app: web.Application):
    """Timers, alarms and reminders: on the device, or on the Mac if none is connected."""
    async def loop():
        while True:
            try:
                for item in skill_timers.due():
                    session = hub.connected()
                    alarms = kernel.module("skill-alarms")
                    if session and hasattr(session.brain, "ring"):
                        asyncio.ensure_future(session.brain.ring(item))
                    elif alarms:
                        asyncio.ensure_future(alarms.ring_on_mac(item))
            except Exception as e:
                logging.warning("timers: %r", e)
            await asyncio.sleep(0.5)

    app["timers"] = asyncio.ensure_future(loop())


def _while_on(handler, plugin):
    async def guarded(request):
        if not kernel.enabled(plugin):  # turned off since: as if it weren't there
            raise web.HTTPNotFound()
        return await handler(request)
    return guarded


def application() -> web.Application:
    app = web.Application(middlewares=[no_cache], client_max_size=20 * 1024 * 1024)  # photos
    app.router.add_get("/", index)
    app.router.add_get("/monitor", monitor)
    app.router.add_post("/offer", offer)
    app.router.add_get("/video.mjpg", video_mjpeg)
    app.router.add_get("/status", status)
    app.router.add_get("/config", page_config)
    app.router.add_get("/skin/{name}/{path:.+}", skin_file)
    app.router.add_get("/lab", lab)
    app.router.add_route("*", "/mcp", mcp_server.endpoint)
    kernel.load_all()
    for method, path, handler, plugin in ROUTES:  # the plugins' own
        app.router.add_route(method, path, _while_on(handler, plugin))
    app.router.add_static("/web/", WEB)
    app.on_shutdown.append(on_shutdown)
    app.on_startup.append(ring_when_due)
    return app
