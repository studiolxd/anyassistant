"""The device's page: what a tablet or phone opens at http://<mac>:8080 (web/: plain
JavaScript for old Chrome), with its texts (locales/, «ui») and its look, the themes
(themes.py; the system's in themes/, yours in «themes_dir»).

It is one client of Jarvis among others (native apps would be more): it brings «/»,
/web/…, /config (what the page needs: texts, settings, theme; other plugins add to it
with @web.config) and /theme/…, the screen's options, and the theme tools for the LLM.
"""

from pathlib import Path

from aiohttp import web as http

import i18n
import kernel
import options
import settings
import web
from options import Option

from . import themes

HERE = Path(__file__).parent
WEB = HERE / "web"

for option in (
    Option("theme", themes.DEFAULT, "the screen's look: eyes, orb, minimal, bedside or yours (a device's ?theme= wins)",
           "screen", "choice", lambda: list(themes.available()), live=True),
    Option("theme_options", None, 'the theme\'s options: {"accent": "#ff7a45"}', "screen", "dict", live=True,
           empty="the theme's own"),
    Option("themes_dir", None, "your themes (default: themes in your data folder)", "screen",
           empty="themes in your data folder"),
    Option("video", "auto", "camera quality; auto: each device by its memory (a device's ?video= wins)", "screen",
           "choice", ["auto", "normal", "low", "off"], live=True),
    Option("show_time", True, "the time while asleep", "screen", "bool", live=True, screen=True),
    Option("show_date", True, "the date while asleep", "screen", "bool", live=True, screen=True),
    Option("show_hint", True, "«Say “Hey, {name}”» while asleep", "screen", "bool", live=True, screen=True),
    Option("show_status", True, "«Listening», «Thinking…» while awake", "screen", "bool", live=True, screen=True),
    Option("show_heard", True, "what you said", "screen", "bool", live=True, screen=True),
    Option("show_answer", True, "what it answers", "screen", "bool", live=True, screen=True),
    Option("history", 2, "earlier sentences kept on screen", "screen", "int", live=True, screen=True),
    Option("show_timers", True, "running timers, alarms and reminders", "screen", "bool", live=True, screen=True),
    Option("show_stats", False, "the connection's RTT, jitter and losses", "screen", "bool", live=True, screen=True),
    Option("clock", "auto", "12 or 24 hours (auto: the language's)", "screen", "choice", ["auto", "12", "24"],
           live=True, screen=True),
):
    options.add(option)


LOCAL = {"127.0.0.1", "::1"}


@web.route("GET", "/")
async def _index(request):
    # With the plugin «https», another device on plain HTTP goes to the HTTPS page: on HTTP the
    # browser doesn't let it use the microphone (it would ask for Chrome's flag). The Mac stays.
    https = kernel.module("https")
    if https and not request.secure and request.remote not in LOCAL:
        raise http.HTTPFound(https.address(request.url.raw_host or https.NAME, request.path_qs))
    return web.page(WEB / "index.html")


@web.route("GET", "/web/{path:.+}")
async def _web_file(request):
    target = (WEB / request.match_info["path"]).resolve()
    if WEB.resolve() not in target.parents or not target.is_file():
        return http.Response(status=404)
    return http.FileResponse(target)


@web.route("GET", "/theme/{name}/{path:.+}")
async def _theme_file(request):
    """A theme's stylesheet, images, fonts or sounds: only from inside its folder."""
    path = themes.asset(request.match_info["name"], request.match_info["path"])
    return http.FileResponse(path) if path else http.Response(status=404)


@web.route("GET", "/config")
async def _config(request):
    """What the page needs: its texts in the active language (locale «ui»), the settings and the theme
    (?theme=: this device's own), and what other plugins add (@web.config)."""
    chosen = request.query.get("theme", "")
    return http.json_response({
        "lang": i18n.L.code, "ui": i18n.L.data["ui"],
        "name": settings.get("name"), "video": settings.get("video"),
        "theme": themes.for_page(chosen if chosen in themes.available() else settings.get("theme"), i18n.L.code),
        "themes": [{"name": name, "title": themes.manifest(name).get("name", name),
                   "description": themes.manifest(name).get("description", "")} for name in themes.available()],
        "screen": {key: settings.get(key) for key in options.SCREEN},
        # How it is woken, as the screen says it («Ey, Eva»): for the demo and the themes page, before a brain says it.
        "wake_phrase": i18n.L.text("wake.phrase", "Hey, {name}").format(name=(settings.get("name") or "Jarvis").title()),
        **web.contributed(request),
    })
