"""The device's page: what a tablet or phone opens at http://<mac>:8080 (web/: plain
JavaScript for old Chrome), with its texts (locales/, «ui») and its look, the skins
(skins.py; the system's in skins/, yours in «skins_dir»).

It is one client of Jarvis among others (native apps would be more): it brings «/»,
/web/…, /config (what the page needs: texts, settings, skin; other plugins add to it
with @web.config) and /skin/…, the screen's options, and the skin tools for the LLM.
"""

from pathlib import Path

from aiohttp import web as http

import i18n
import options
import settings
import web
from options import Option

from . import skins

HERE = Path(__file__).parent
WEB = HERE / "web"

for option in (
    Option("skin", skins.DEFAULT, "the screen's look: eyes, orb, minimal, bedside or yours (a device's ?skin= wins)",
           "screen", "choice", lambda: list(skins.available()), live=True),
    Option("skin_options", None, 'the skin\'s options: {"accent": "#ff7a45"}', "screen", "dict", live=True,
           empty="the skin's own"),
    Option("skins_dir", None, "your skins (default: skins in your data folder)", "screen",
           empty="skins in your data folder"),
    Option("video", "auto", "camera quality; auto: each device by its memory (a device's ?video= wins)", "screen",
           "choice", ["auto", "normal", "low", "off"], live=True),
    Option("show_time", True, "the time while asleep", "screen", "bool", live=True, screen=True),
    Option("show_date", True, "the date while asleep", "screen", "bool", live=True, screen=True),
    Option("show_hint", True, "«Say Hey Jarvis» while asleep", "screen", "bool", live=True, screen=True),
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


@web.route("GET", "/")
async def _index(request):
    return web.page(WEB / "index.html")


@web.route("GET", "/web/{path:.+}")
async def _web_file(request):
    target = (WEB / request.match_info["path"]).resolve()
    if WEB.resolve() not in target.parents or not target.is_file():
        return http.Response(status=404)
    return http.FileResponse(target)


@web.route("GET", "/skin/{name}/{path:.+}")
async def _skin_file(request):
    """A skin's stylesheet, images, fonts or sounds: only from inside its folder."""
    path = skins.asset(request.match_info["name"], request.match_info["path"])
    return http.FileResponse(path) if path else http.Response(status=404)


@web.route("GET", "/config")
async def _config(request):
    """What the page needs: its texts in the active language (locale «ui»), the settings and the skin
    (?skin=: this device's own), and what other plugins add (@web.config)."""
    chosen = request.query.get("skin", "")
    return http.json_response({
        "lang": i18n.L.code, "ui": i18n.L.data["ui"],
        "name": settings.get("name"), "video": settings.get("video"),
        "skin": skins.for_page(chosen if chosen in skins.available() else settings.get("skin"), i18n.L.code),
        "skins": [{"name": name, "title": skins.manifest(name).get("name", name),
                   "description": skins.manifest(name).get("description", "")} for name in skins.available()],
        "screen": {key: settings.get(key) for key in options.SCREEN},
        **web.contributed(request),
    })
