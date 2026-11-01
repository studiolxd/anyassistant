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

import asyncio
import logging
import os
import signal
import sys

from aiohttp import web as aiohttp_web

import i18n
import options
import settings
import web
import brain



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

    if sys.platform == "win32":  # Windows' console and redirected logs aren't UTF-8: «», →, ñ
        for stream in (sys.stdout, sys.stderr):
            stream.reconfigure(encoding="utf-8", errors="replace")
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

    web.brain = brain.create(args.mode, args)  # the plugin of that kind builds its engines

    app = web.application()

    async def listen_for_sighup(app):
        """bin/anyassistant restart (SIGHUP; Windows has no such signal: «restart» by voice is web.stop)."""
        if hasattr(signal, "SIGHUP"):
            asyncio.get_running_loop().add_signal_handler(signal.SIGHUP, lambda: web.stop(restart=True))

    app.on_startup.append(listen_for_sighup)

    async def follow_the_app(app):
        """Started by the AnyAssistant app: if the app goes (quit, killed), so does the server. An
        orphan would keep the port without the app's Local Network permission: no device could talk."""
        if not os.environ.get("ANYASSISTANT_APP"):
            return
        parent = os.getppid()

        async def watch():
            while os.getppid() == parent:
                await asyncio.sleep(2)
            logging.info("the app is gone: stopping")
            web.stop()

        app["follow_the_app"] = asyncio.ensure_future(watch())

    app.on_startup.append(follow_the_app)

    # Short shutdown_timeout: the camera monitor (/video.mjpg) never ends by itself.
    aiohttp_web.run_app(app, host=args.host, port=args.port, shutdown_timeout=3)
    if web.restarting:
        logging.info("restarting…")
        argv = sys.argv
        if settings.load().get("language", i18n.L.code) != i18n.L.code:
            argv = settings.without_option(argv, "--lang")  # changed by voice: settings.json wins
        os.execv(sys.executable, [sys.executable, *argv])


if __name__ == "__main__":
    main()
