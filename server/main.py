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
import pairing
import settings
import skills
import skins
import stt
import tools
from skills import timers as skill_timers
import tts
import wake
from brain import assistant, transcriber
from brain.parrot import Parrot
from transport import Session

WEB = Path(__file__).resolve().parent.parent / "web"
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
    parser = argparse.ArgumentParser()
    parser.add_argument("--name", default="Jarvis", help="the assistant's name: wake word, page, LLM")
    parser.add_argument("--instructions", default=None, help="more instructions for the LLM (who you are, how to talk…)")
    parser.add_argument("--skin", default="eyes", help="the screen's look: a folder of skins/ or skins_dir (?skin= wins)")
    parser.add_argument("--skin-options", type=json.loads, default=None, help='the skin\'s options: {"accent": "#ff7a45"}')
    parser.add_argument("--skins-dir", default=None, help="your skins (default: skins.local/)")
    parser.add_argument("--video", choices=["auto", "normal", "low", "off"], default="auto",
                        help="camera quality; auto: each device by its memory (?video= wins)")
    parser.add_argument("--detail", default="neutral",
                        help="how much it says: concise, neutral, detailed or one of «detail_levels»")
    parser.add_argument("--detail-levels", type=json.loads, default=None,
                        help='more levels, or other texts for these: {"name": "instruction for the prompt"}')
    parser.add_argument("--memory", choices=["off", "explicit", "auto"], default="off",
                        help="remember across conversations: only when asked (explicit) or also on its own (auto)")
    parser.add_argument("--eyes", action=argparse.BooleanOptionalAction, default=False,
                        help="it may look through the device's camera (with Claude)")
    parser.add_argument("--pairing", action=argparse.BooleanOptionalAction, default=False,
                        help="only devices paired with a code (bin/jarvis pair) may connect")
    parser.add_argument("--log-transcripts", action=argparse.BooleanOptionalAction, default=False,
                        help="write what it hears and says to the log (to debug); off: only lengths")
    parser.add_argument("--confirm-wait", type=float, default=120, help="seconds to answer «yes» to an action")
    parser.add_argument("--confirm-valid", type=float, default=60, help="seconds a «yes» stays valid")
    # The screen
    parser.add_argument("--show-time", action=argparse.BooleanOptionalAction, default=True, help="the time while asleep")
    parser.add_argument("--show-date", action=argparse.BooleanOptionalAction, default=True, help="the date while asleep")
    parser.add_argument("--show-hint", action=argparse.BooleanOptionalAction, default=True, help="«Say Hey Jarvis» while asleep")
    parser.add_argument("--show-status", action=argparse.BooleanOptionalAction, default=True, help="«Listening», «Thinking…» while awake")
    parser.add_argument("--show-heard", action=argparse.BooleanOptionalAction, default=True, help="what you said")
    parser.add_argument("--show-answer", action=argparse.BooleanOptionalAction, default=True, help="what it answers")
    parser.add_argument("--history", type=int, default=2, help="earlier sentences kept on screen")
    parser.add_argument("--show-stats", action=argparse.BooleanOptionalAction, default=False, help="the connection's RTT, jitter and losses")
    parser.add_argument("--clock", choices=["auto", "12", "24"], default="auto", help="12 or 24 hours (auto: the language's)")
    # Sounds and behavior
    parser.add_argument("--beeps", action=argparse.BooleanOptionalAction, default=True, help="a beep when it wakes up and when it falls asleep")
    parser.add_argument("--fillers", action=argparse.BooleanOptionalAction, default=True, help="«One moment, let me check» when a tool is slow")
    parser.add_argument("--voice-interrupt", action=argparse.BooleanOptionalAction, default=True, help="«Jarvis, stop» while it speaks")
    parser.add_argument("--tap-to-stop", action=argparse.BooleanOptionalAction, default=True, help="tapping the screen stops it talking")
    parser.add_argument("--read-photo", action=argparse.BooleanOptionalAction, default=True, help="a full-resolution photo when asked to read")
    parser.add_argument("--skills", action=argparse.BooleanOptionalAction, default=True,
                        help="time, date, timers, alarms, reminders, sums, units and volume, without the LLM")
    parser.add_argument("--interpreter", choices=["auto", "apple", "off"], default="auto",
                        help="Apple's local model for skills said in unusual ways (auto: if this Mac has it)")
    parser.add_argument("--volume", type=int, default=100, help="its voice and sounds, 5–100 %")
    parser.add_argument("--ring-seconds", type=int, default=60, help="how long an alarm rings if nobody stops it")
    parser.add_argument("--snooze-minutes", type=int, default=5, help="«snooze» without saying how long")
    parser.add_argument("--show-timers", action=argparse.BooleanOptionalAction, default=True, help="running timers, alarms and reminders on screen")
    parser.add_argument("--memory-facts", type=int, default=50, help="facts before the LLM compacts them")
    parser.add_argument("--memory-conversations", type=int, default=10, help="conversation summaries kept")
    parser.add_argument("--memory-days", type=int, default=30, help="days a conversation summary is kept")
    parser.add_argument("--host", default="0.0.0.0")
    parser.add_argument("--port", type=int, default=8080)
    parser.add_argument("--lang", dest="language", default=None, help=f"language: {', '.join(i18n.available())} (default: settings.json or the Mac's)")
    parser.add_argument("--mode", choices=["parrot", "transcribe", "assistant"], default="assistant")
    parser.add_argument("--stt", default="parakeet", help=f"plugin: {', '.join(stt.available())}")
    parser.add_argument("--stt-model", default=None)
    parser.add_argument("--llm", default="claude", help=f"plugin: {', '.join(llm.available())}")
    parser.add_argument("--llm-model", default=None)
    parser.add_argument("--mcp", default=None, help=".mcp.json with the MCP servers (default: the project's)")
    parser.add_argument("--tts", default="avspeech", help=f"voice: {', '.join(tts.available())} or none")
    parser.add_argument("--voice", default=None, help="the plugin's voice (default: the language's)")
    parser.add_argument("--rate", type=int, default=None, help="words per minute")
    parser.add_argument("--echo-guard", type=float, default=1.2, help="seconds without listening after speaking")
    parser.add_argument("--wake", default="whisper", help=f"wake word: {', '.join(wake.available())} or none")
    parser.add_argument("--wake-word", default=None, help="the word or model (jarvis, hey_jarvis, alexa…)")
    parser.add_argument("--threshold", type=float, default=None, help="each wake plugin has its own default")
    parser.add_argument("--record", default=None, help="saves everything that arrives to a WAV (debugging)")
    parser.add_argument("--silence", type=float, default=0.6, help="seconds of silence that end a sentence")
    parser.add_argument("--follow-up", type=float, default=20,
                        help="seconds it keeps listening without its name after it last spoke or heard you")
    parser.add_argument("--ignore-others", action=argparse.BooleanOptionalAction, default=True,
                        help="the LLM stays quiet when what it hears is clearly not for it")
    preferences = settings.load()
    if "face" in preferences:  # before skins, «face» chose between the eyes and the orb
        preferences.setdefault("skin", preferences.pop("face"))
    known = {a.dest for a in parser._actions}
    for key in preferences.keys() - known:
        print(f"settings.json: unknown key «{key}» (ignored)", file=sys.stderr)
    parser.set_defaults(**{k: v for k, v in preferences.items() if k in known})
    args = parser.parse_args()
    settings.active = vars(args)  # skins.available() reads skins_dir
    if args.skin not in skins.available():
        parser.error(f"skin: «{args.skin}» is not one of {', '.join(skins.available())}")
    levels = {**llm.DETAIL_LEVELS, **(args.detail_levels or {})}
    if args.detail not in levels:
        parser.error(f"detail: «{args.detail}» is not one of {', '.join(levels)}")
    for action in parser._actions:  # argparse doesn't check defaults, which come from settings.json
        if action.choices and getattr(args, action.dest) not in action.choices:
            parser.error(f"{action.dest}: «{getattr(args, action.dest)}» is not one of {', '.join(action.choices)}")

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
            options = {"word": args.wake_word}
            if args.threshold is not None:
                options["threshold"] = args.threshold
            logging.info("wake word: %s", wake.create(args.wake, **options).phrase)
            wake_factory = lambda: wake.create(args.wake, **options)  # noqa: E731
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
                            asyncio.ensure_future(skills.ring_on_mac(item))
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
