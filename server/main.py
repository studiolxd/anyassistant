"""Server: serves the phone's web page and does the WebRTC signaling.

    uv run server/main.py                       # assistant: Parakeet + Claude (CLI) + AVSpeech
    uv run server/main.py --lang es             # language (default: the Mac's, if available)
    uv run server/main.py --llm apple           # Apple's model, local
    uv run server/main.py --voice Eddy          # another macOS voice; --tts none for no voice
    uv run server/main.py --silence 0.45        # ends sentences sooner (faster)
    uv run server/main.py --mode transcribe     # only transcribes
    uv run server/main.py --mode parrot         # repeats what it hears (audio test)
    uv run server/main.py --wake none           # no wake word
    uv run server/main.py --stt|--llm|--tts X   # any module in server/stt|llm|tts/
"""

import argparse
import asyncio
import json
import logging
import os
import signal
import sys
import uuid
from html import escape
from pathlib import Path

from aiohttp import web

import eyes
import i18n
import llm
import mcp_server
import options
import pairing
import paths
import settings
import skills
import skins
import stt
import tools
from skills import alarms
from skills import timers as skill_timers
import tts
import wake
from brain import assistant, transcriber
from brain.parrot import Parrot
from transport import Session

WEB = paths.WEB
sessions: dict[str, Session] = {}
brain_factory = Parrot  # set by main() according to --mode
close_on_exit = []  # coroutines to await when stopping (plugin processes)
restart = False  # SIGHUP («restart» by voice): stop cleanly and start again


def is_allowed(request: web.Request) -> bool:
    return pairing.allowed(request.remote, request.cookies.get(pairing.COOKIE))


def not_paired() -> web.Response:
    return web.json_response({"pairing": True}, status=403)


async def offer(request: web.Request) -> web.Response:
    if not is_allowed(request):
        return not_paired()
    data = await request.json()
    session = Session(uuid.uuid4().hex[:6], brain_factory)
    # A single phone: the new connection replaces the previous ones.
    for old in list(sessions.values()):
        await old.close()
    sessions.clear()
    sessions[session.id] = session
    answer = await session.answer(data["sdp"], data["type"])
    return web.json_response({"sdp": answer.sdp, "type": answer.type})


def current_session() -> Session | None:
    return next(iter(sessions.values()), None)


async def video_mjpeg(request: web.Request) -> web.StreamResponse:
    """What the camera sees, to watch it from the Mac's browser."""
    if not is_allowed(request):
        return not_paired()
    response = web.StreamResponse(headers={"Content-Type": "multipart/x-mixed-replace; boundary=frame"})
    await response.prepare(request)
    while True:
        session = current_session()
        image = session.jpeg() if session else None
        if image:
            await response.write(b"--frame\r\nContent-Type: image/jpeg\r\n\r\n" + image + b"\r\n")
        await asyncio.sleep(1 / 10)


async def status(request: web.Request) -> web.Response:
    if not is_allowed(request):
        return not_paired()
    session = current_session()
    return web.json_response({
        "connected": bool(session and session.pc.connectionState == "connected"),
        "frames": session.frames if session else 0,
    })


async def eyes_image(request: web.Request) -> web.StreamResponse:
    """The photo it just looked at, for the screen (paired devices only)."""
    if not is_allowed(request) or not eyes.enabled() or not eyes.FRAME.exists():
        return web.Response(status=404)
    return web.FileResponse(eyes.FRAME)


async def photo(request: web.Request) -> web.Response:
    """The full-resolution photo the device took when asked to (eyes.photo)."""
    if not is_allowed(request):
        return not_paired()
    eyes.photo_arrived(int(request.query.get("id", 0)), await request.read(), request.query.get("how", "?"))
    return web.Response(status=204)


async def skin_file(request: web.Request) -> web.StreamResponse:
    """A skin's stylesheet, images, fonts or sounds: only from inside its folder."""
    path = skins.asset(request.match_info["name"], request.match_info["path"])
    return web.FileResponse(path) if path else web.Response(status=404)


async def lab(request: web.Request) -> web.Response:
    """The skins lab: every state of a skin at once, reloading when its files change."""
    return page("lab.html")


async def config(request: web.Request) -> web.Response:
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
        "paired": is_allowed(request),
    })


async def new_pairing_code(request: web.Request) -> web.Response:
    """For bin/jarvis pair: only from the Mac itself."""
    if request.remote not in pairing.LOCAL:
        return web.json_response({}, status=403)
    if request.query.get("forget"):
        pairing.unpair_all()
        return web.json_response({"forgotten": True})
    return web.json_response({"code": pairing.new_code(), "seconds": pairing.CODE_LIFETIME,
                              "pairing": bool(settings.get("pairing"))})


async def pair(request: web.Request) -> web.Response:
    data = await request.json()
    token = pairing.pair(data.get("code", ""), request.headers.get("User-Agent", "?"))
    if not token:
        return web.json_response({"paired": False}, status=403)
    response = web.json_response({"paired": True})
    response.set_cookie(pairing.COOKIE, token, max_age=10 * 365 * 24 * 3600, httponly=True, samesite="Strict")
    return response


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
    steps = [s.close() for s in sessions.values()] + [close() for close in close_on_exit]
    for step in steps:
        try:
            await asyncio.wait_for(step, 5)
        except Exception as e:
            logging.warning("while closing: %r", e)


def main():
    parser = options.parser()
    preferences = settings.load()
    if "face" in preferences:  # before skins, «face» chose between the eyes and the orb
        preferences.setdefault("skin", preferences.pop("face"))
    known = {a.dest for a in parser._actions}
    for key in preferences.keys() - known:
        print(f"settings.json: unknown key «{key}» (ignored)", file=sys.stderr)
    parser.set_defaults(**{k: v for k, v in preferences.items() if k in known})
    args = parser.parse_args()
    settings.active = vars(args)  # the skins' list reads skins_dir
    problems = options.check(vars(args))
    if problems:
        parser.error("; ".join(problems))

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(message)s")
    logging.getLogger("aioice").setLevel(logging.WARNING)
    i18n.use(args.language or i18n.detect())  # before the plugins: they take its language and voice
    args.language = i18n.L.code
    args.voice = settings.effective("voice", args.voice, i18n.L.code)
    args.instructions = settings.effective("instructions", args.instructions, i18n.L.code)
    settings.active = vars(args)
    settings.fixed = {
        action.dest for action in parser._actions
        if any(arg == option or arg.startswith(option + "=") for option in action.option_strings for arg in sys.argv[1:])
    }

    global brain_factory
    ear = {"record": args.record, "silence": args.silence, "follow_up": args.follow_up}
    if args.mode in ("transcribe", "assistant"):
        engine = stt.create(args.stt, language=i18n.L.stt_language, model=args.stt_model)
        logging.info("loading STT %s (%s)…", engine.name, engine.model)
        engine.warm_up()
        wake_factory = None
        if args.wake != "none":
            wake_options = {"word": args.wake_word}
            if args.threshold is not None:
                wake_options["threshold"] = args.threshold
            logging.info("wake word: %s", wake.create(args.wake, **wake_options).phrase)
            wake_factory = lambda: wake.create(args.wake, **wake_options)  # noqa: E731
        if args.mode == "assistant":
            model = llm.create(args.llm, model=args.llm_model, mcp=args.mcp)
            logging.info("LLM: %s (%s)", model.name, model.model)
            voice = None
            if args.tts != "none":
                voice = tts.create(args.tts, voice=args.voice, rate=args.rate)
                logging.info("voice: %s (%s)", voice.name, voice.voice)
                voice.warm_up()

                async def close_voice():
                    voice.close()

                close_on_exit.append(close_voice)
            brain_factory = assistant.create(engine, model, voice, wake_factory, ear, args.echo_guard)
            close_on_exit.append(model.close)
        else:
            brain_factory = transcriber.create(engine, wake_factory, ear)
    else:
        brain_factory = Parrot

    eyes.source = lambda: (session := current_session()) and session.jpeg()
    tools.session = current_session

    def timers_changed():
        session = current_session()
        if session and hasattr(session.brain, "send_timers"):
            session.brain.send_timers()

    skill_timers.changed = timers_changed
    eyes.ask_device = lambda message: bool((session := current_session()) and session.send(message) is None)
    app = web.Application(middlewares=[no_cache], client_max_size=20 * 1024 * 1024)  # photos
    app.router.add_get("/", index)
    app.router.add_get("/monitor", monitor)
    app.router.add_post("/offer", offer)
    app.router.add_get("/video.mjpg", video_mjpeg)
    app.router.add_get("/status", status)
    app.router.add_get("/config", config)
    app.router.add_get("/skin/{name}/{path:.+}", skin_file)
    app.router.add_get("/lab", lab)
    app.router.add_get("/eyes.jpg", eyes_image)
    app.router.add_post("/photo", photo)
    app.router.add_route("*", "/mcp", mcp_server.endpoint)
    app.router.add_post("/pairing", new_pairing_code)
    app.router.add_post("/pair", pair)
    app.router.add_static("/web/", WEB)
    app.on_shutdown.append(on_shutdown)

    async def listen_for_sighup(app):
        def on_sighup():
            global restart
            restart = True
            raise web.GracefulExit()  # like Ctrl+C: closes sessions and plugins

        asyncio.get_running_loop().add_signal_handler(signal.SIGHUP, on_sighup)

    app.on_startup.append(listen_for_sighup)

    async def ring_when_due(app):
        """Timers, alarms and reminders: on the device, or on the Mac if none is connected."""
        async def loop():
            while True:
                try:
                    for item in skill_timers.due():
                        session = current_session()
                        if session and hasattr(session.brain, "ring") and session.pc.connectionState == "connected":
                            asyncio.ensure_future(session.brain.ring(item))
                        else:
                            asyncio.ensure_future(alarms.ring_on_mac(item))
                except Exception as e:
                    logging.warning("timers: %r", e)
                await asyncio.sleep(0.5)

        app["timers"] = asyncio.ensure_future(loop())

    app.on_startup.append(ring_when_due)
    # Short shutdown_timeout: the camera monitor (/video.mjpg) never ends by itself.
    web.run_app(app, host=args.host, port=args.port, shutdown_timeout=3)
    if restart:
        logging.info("restarting…")
        argv = sys.argv
        if settings.load().get("language", i18n.L.code) != i18n.L.code:
            argv = settings.without_option(argv, "--lang")  # changed by voice: settings.json wins
        os.execv(sys.executable, [sys.executable, *argv])


if __name__ == "__main__":
    main()
