"""The device's page: what a tablet or phone opens at http://<mac>:8080 (web/: plain
JavaScript for old Chrome), with its texts (locales/, «ui») and its look, the themes
(themes.py; the system's in themes/, yours in «themes_dir»).

It is one client of Jarvis among others (native apps would be more): it brings «/»,
/web/…, /config (what the page needs: texts, settings, theme; other plugins add to it
with @web.config) and /theme/…, the screen's options, and the theme tools for the LLM.

And /connect, what the QR in «Conectar otro dispositivo» opens (connect_url): on a phone or
tablet it offers the app (anyassistant://connect?…, app_url: the iPhone and Android apps pair
by themselves with it) and, in the browser, pairs with the code and goes on to the page (the
HTTPS one, after its certificate, when the plugin «https» is on). Plain HTML, no script: the
oldest browsers too.
"""

import html
import re
from pathlib import Path
from urllib.parse import quote, urlencode

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
    Option("theme", themes.DEFAULT, "the screen's look: eyes, one from the community or yours (a device's ?theme= wins)",
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


# --- Connecting a device: the QR's page ---

def connect_url(address: str, port: int, code: str | None = None) -> str:
    """What the QR says: this server itself, by its address now (old devices don't resolve
    anyassistant.local; the Mac app and the admin page make it when shown, so a changed address
    doesn't matter), with the pairing code if there is one. Plain HTTP even with the plugin «https»
    on: it works before the device has the certificate (/connect gives it first, then the HTTPS page),
    and the apps fetch the authority over HTTP themselves."""
    return f"http://{address}:{port}/connect" + (f"?code={quote(code)}" if code else "")


def app_url(host: str, port: int, code: str | None, server: str, name: str) -> str:
    """anyassistant://connect?host=…&port=…&code=…&server=…&name=…: the iPhone and Android apps open
    it (also read from the QR with «Escanear código») and pair with nothing to type."""
    query = {"host": host, "port": port}
    if code:
        query["code"] = code
    query.update(server=server, name=name)
    return "anyassistant://connect?" + urlencode(query)


def _mobile(agent: str) -> bool:
    """Whether it looks like a phone or tablet (the app exists for it)."""
    return bool(re.search(r"Mobile|Android|iPhone|iPad|iPod|Tablet", agent))


def _android_app_link(link: str, fallback: str) -> str:
    """Chrome on Android: the app if it's installed, else back to this page (a bare anyassistant://
    link does nothing there without the app)."""
    inner = link[len("anyassistant://"):]
    return f"intent://{inner}#Intent;scheme=anyassistant;package=com.anyassistant;S.browser_fallback_url={quote(fallback, safe='')};end"


def _connect_page(request, code: str, problem: bool):
    """The page in its state: not paired yet (the code, to go on in the browser; the app, on a phone
    or tablet), or paired (the app; the certificate first with HTTPS; the page)."""
    pairing = kernel.module("pairing")
    https = kernel.module("https")
    agent = request.headers.get("User-Agent", "")
    paired = pairing is None or pairing.allowed(request.remote, request.cookies.get(pairing.COOKIE))
    host = request.url.host or "anyassistant.local"
    port = settings.get("port") or 8080
    page = https.address(host) if https else "/"
    if paired and not https and not _mobile(agent):
        raise http.HTTPFound("/")
    t = lambda key: i18n.L.text(f"connect.{key}", key)  # noqa: E731
    name = settings.get("name") or "Jarvis"
    link = app_url(host, port, None if paired else code, web.identity(), name)
    if "Android" in agent:
        link = _android_app_link(link, str(request.url))
    e = html.escape
    parts = [f"<h1>{e(t('title'))}</h1>"]
    if _mobile(agent):
        parts.append(f'<a class="button" href="{e(link)}">{e(t("app"))}</a>'
                     f'<p class="muted">{e(t("app_note"))}</p>')
    if not paired:
        parts.append(f'<form method="post" action="/connect"><p>{e(t("browser"))}</p>'
                     f'<input name="code" inputmode="numeric" autocomplete="one-time-code" maxlength="6" value="{e(code)}">'
                     + (f'<p class="error">{e(t("wrong"))}</p>' if problem else "")
                     + f'<button type="submit">{e(t("continue") if _mobile(agent) else t("connect"))}</button></form>')
    else:
        if pairing is None:
            parts.append(f'<p class="muted">{e(t("no_code"))}</p>')
        if https:
            parts.append(f'<h2>{e(t("certificate"))}</h2><p>{e(t("certificate_how"))}</p>'
                         f'<a class="button quiet" href="/https/ca.crt">{e(t("certificate_get"))}</a>'
                         f'<p class="muted">{e(t("certificate_android"))}</p><h2>{e(t("then"))}</h2>')
        parts.append(f'<a class="button" href="{e(page)}">{e(t("open"))}</a>')
    body = (WEB / "connect.html").read_text().replace("{lang}", i18n.L.code).replace("{title}", e(t("title")))
    return http.Response(text=body.replace("{body}", "\n".join(parts)), content_type="text/html")


@web.route("GET", "/connect")
async def _connect(request):
    return _connect_page(request, request.query.get("code", ""), problem=False)


@web.route("POST", "/connect")
async def _connect_pair(request):
    """The form: pairs this browser with the code (one device per code) and shows what's next."""
    pairing = kernel.module("pairing")
    data = await request.post()
    code = str(data.get("code", "")).strip()
    if pairing is not None and not pairing.allowed(request.remote, request.cookies.get(pairing.COOKIE)):
        token = pairing.pair(code, request.headers.get("User-Agent", "?"))
        if not token:
            return _connect_page(request, "", problem=True)
        return pairing.welcome(http.HTTPFound("/connect"), token)
    raise http.HTTPFound("/connect")


@web.route("GET", "/")
async def _index(request):
    # With the plugin «https», another device on plain HTTP goes to the HTTPS page: on HTTP the
    # browser doesn't let it use the microphone (it would ask for Chrome's flag). The Mac stays, and
    # so does an app's view of its theme (?app: the app has the microphone; its address is the app's).
    https = kernel.module("https")
    if https and not request.secure and request.remote not in LOCAL and "app" not in request.query:
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
                   "description": themes.description(name, i18n.L.code)} for name in themes.available()],
        "screen": {key: settings.get(key) for key in options.SCREEN},
        # How it is woken, as the screen says it («Ey, Eva»): for the demo and the themes page, before a brain says it.
        "wake_phrase": i18n.L.text("wake.phrase", "Hey, {name}").format(name=(settings.get("name") or "Jarvis").title()),
        **web.contributed(request),
    })
