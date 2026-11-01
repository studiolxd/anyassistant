"""Admin: what the AnyAssistant app shows and changes, and the same as a web page (/admin) for
Windows and Linux, and a Linux with no screen. From this computer itself, or from a browser
given an admin code (6 digits, 5 minutes, one browser: the page here, or
`bin/anyassistant admin-code` over SSH); a device paired to talk can't administer.

    GET  /admin            the page (plugins/admin/web)
    POST /admin/login      {"code"} → that browser is an admin (a cookie; its hash in admins.json)
    POST /admin/code       a code for another browser (the owner only)
    GET  /admin/admins     the admin browsers; POST {"forget": id} or {"logout": true}
    GET  /admin/status     name, version, addresses, ports: to pair a device
    GET  /admin/qr?text=   a QR code (SVG)
    POST /admin/restart    restarts the server
    POST /admin/stop       stops it, cleanly (the Windows and Linux app: no signals there)

    GET  /admin/settings   the options by group, each with its value, kind, choices and help
                           (in the active language: locale «options», «groups»)
    POST /admin/settings   {"name": value, …} → saved; {"restart": true} if one needs it
    GET  /admin/plugins    every plugin: on, locked, why it can't work here, what it lacks
    POST /admin/plugins    {"id": true|false} → saved; whether packages must be installed
                           (bin/anyassistant setup packages) or the server restarted

From the Mac the user is the owner: unlike by voice, any plugin can be turned off here
(the app warns about the security and locked ones).
"""

import hashlib
import json
import logging
import secrets
import socket
import time
from pathlib import Path

from aiohttp import web as http

import i18n
import kernel
import options
import paths
import settings
import web

log = logging.getLogger("admin")

ENGINES = {"brain", "stt", "wake", "llm", "tts", "vad"}  # chosen at start: a change restarts


_local = web.only_the_owner  # this computer, or a browser given an admin code


def _json(value):
    try:
        json.dumps(value)
        return value
    except TypeError:
        return str(value)


def _named(text: str) -> str:
    """A help that names the assistant («Say “Hey, {name}”») says its name: «Hey, Eva»."""
    return text.replace("{name}", settings.get("name") or "Jarvis")


def _value(option):
    """What settings.json says (or the default): what the field shows."""
    return _json(settings.load().get(option.name, option.default))


def _current(option):
    """What the server uses now: for an empty one, what it chose (the language's voice: «Mónica»)."""
    value = settings.get(option.name, option.default)
    if option.name == "voice" and not value:
        value = i18n.L.tts_voice
    return _json(value)


def _choices(option):
    try:
        return [c for c in option.options()] if option.kind == "choice" else None
    except Exception:  # a list that couldn't be made now (a plugin off…)
        return None


def _labels(option) -> dict | None:
    """How each choice is shown, in the active language (locale «choices.<option>.<value>»);
    one without a text, as it is."""
    found = _choices(option)
    if found is None:
        return None
    if option.name == "language":
        return {str(c): i18n.native_name(c) for c in found}  # «English», «Español»
    return {str(c): i18n.L.text(f"choices.{option.name}.{c}", str(c)) for c in found}


@web.route("GET", "/admin/settings")
@_local
async def _settings(request):
    groups = [{"id": g, "title": i18n.L.text(f"groups.{g}", title)} for g, title in options.GROUPS.items()
              if g != "plugins"]
    found = [{"name": o.name, "group": o.group, "kind": o.kind, "live": o.live,
              "help": _named(i18n.L.text(f"options.{o.name}", o.help)), "default": _value_default(o),
              "value": _value(o), "current": _current(o), "choices": _choices(o), "labels": _labels(o),
              "empty": i18n.L.text(f"options_empty.{o.name}", o.empty) if o.empty else ""}
             for o in options.OPTIONS if o.group != "plugins"]
    return http.json_response({"groups": groups, "options": found})


def _value_default(option):
    try:
        json.dumps(option.default)
        return option.default
    except TypeError:
        return str(option.default)


@web.route("POST", "/admin/settings")
@_local
async def _save_settings(request):
    changes = await request.json()
    unknown = [k for k in changes if k not in options.BY_NAME]
    if unknown:
        return http.json_response({"error": f"unknown: {', '.join(unknown)}"}, status=400)
    problems = options.check(changes)
    if problems:
        return http.json_response({"error": "; ".join(problems)}, status=400)
    data = settings.load()
    for key, value in changes.items():
        if value is None:
            data.pop(key, None)  # empty: back to its default, not «null»
        else:
            data[key] = value
    settings.PATH.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n")
    settings.refresh()
    restart = any(not options.BY_NAME[k].live for k in changes)
    return http.json_response({"saved": list(changes), "restart": restart})


@web.route("GET", "/admin/plugins")
@_local
async def _plugins(request):
    found = []
    for p in kernel.describe():
        plugin = kernel.plugin(p["id"])
        found.append({**p, "name": i18n.L.text(f"plugins.{p['id']}.0", p["name"]),
                      "description": i18n.L.text(f"plugins.{p['id']}.1", p["description"]),
                      "locked": plugin.locked, "wanted": kernel.wanted(p["id"])})
    return http.json_response({"plugins": found})


@web.route("POST", "/admin/plugins")
@_local
async def _turn(request):
    changes = await request.json()
    chosen = dict(settings.load().get("plugins") or {})
    for plugin_id, on in changes.items():
        if not kernel.plugin(plugin_id):
            return http.json_response({"error": f"no plugin «{plugin_id}»"}, status=400)
        chosen[plugin_id] = bool(on)
    settings.save(plugins=chosen)
    settings.refresh()
    kernel._unfit.clear()
    packages = any(on and any(w.startswith("not installed") for w in kernel.unfit(pid))
                   for pid, on in changes.items())
    restart = packages or any(kernel.plugin(pid).kind in ENGINES for pid in changes)
    return http.json_response({"packages": packages, "restart": restart})


# --- Admin codes: a browser on another computer as the owner ---

FILE = paths.HOME / "admins.json"
COOKIE = "anyassistant_admin"
CODE_LIFETIME = 300  # seconds
CODE_ATTEMPTS = 5
WEB = Path(__file__).parent / "web"
_code: dict = {}


def _hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def admins() -> list[dict]:
    try:
        return json.loads(FILE.read_text())["admins"]
    except (OSError, ValueError, KeyError):
        return []


def _save(found: list[dict]):
    FILE.parent.mkdir(parents=True, exist_ok=True)
    FILE.write_text(json.dumps({"admins": found}))
    FILE.chmod(0o600)


def new_code() -> str:
    global _code
    _code = {"code": f"{secrets.randbelow(10**6):06d}", "until": time.time() + CODE_LIFETIME,
             "attempts": CODE_ATTEMPTS}
    log.info("admin code issued (valid %d s)", CODE_LIFETIME)
    return _code["code"]


def login(code: str, name: str) -> str | None:
    """The browser's token if the code is right; None otherwise (and the attempt counts)."""
    if not _code or time.time() > _code["until"] or _code["attempts"] <= 0:
        return None
    if not secrets.compare_digest(str(code).strip(), _code["code"]):
        _code["attempts"] -= 1
        return None
    _code.clear()  # one browser per code
    token = secrets.token_urlsafe(32)
    _save(admins() + [{"hash": _hash(token), "name": name[:160], "since": time.time()}])
    log.info("a new admin browser: %s", name[:80])
    return token


@web.owner_check
def _admin_browser(request) -> bool:
    token = request.cookies.get(COOKIE)
    return bool(token) and any(secrets.compare_digest(a["hash"], _hash(token)) for a in admins())


@web.route("GET", "/admin")
async def _page(request):
    return web.page(WEB / "index.html")


@web.route("GET", "/admin/web/{file}")
async def _file(request):
    name = request.match_info["file"]
    if name not in {"admin.js", "admin.css", "icon.png"}:
        raise http.HTTPNotFound()
    return http.FileResponse(WEB / name)


@web.route("GET", "/admin/me")
async def _me(request):
    """Whether this browser may administer; the page's texts in the active language."""
    return http.json_response({"owner": web.owner(request), "here": request.remote in web.LOCAL,
                               "lang": i18n.L.code, "texts": i18n.L.data.get("admin_page", {})})


@web.route("POST", "/admin/login")
async def _login(request):
    data = await request.json()
    token = login(data.get("code", ""), request.headers.get("User-Agent", "?"))
    if not token:
        return http.json_response({"owner": False}, status=403)
    response = http.json_response({"owner": True})
    response.set_cookie(COOKIE, token, max_age=365 * 24 * 3600, httponly=True, samesite="Strict",
                        secure=request.secure)
    return response


@web.route("POST", "/admin/code")
@_local
async def _new_code(request):
    return http.json_response({"code": new_code(), "seconds": CODE_LIFETIME})


@web.route("GET", "/admin/admins")
@_local
async def _admins(request):
    yours = _hash(request.cookies.get(COOKIE) or "")
    return http.json_response({"admins": [{"id": a["hash"][:12], "name": a["name"], "since": a["since"],
                                           "you": a["hash"] == yours} for a in admins()]})


@web.route("POST", "/admin/admins")
@_local
async def _change_admins(request):
    data = await request.json()
    if data.get("logout"):
        forget = _hash(request.cookies.get(COOKIE) or "")[:12]
    else:
        forget = str(data.get("forget", ""))
    _save([a for a in admins() if a["hash"][:12] != forget])
    return await _admins(request)


def _addresses() -> list[str]:
    https = kernel.module("https")
    if https:
        return [a for a in https.addresses() if a != "127.0.0.1"]
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
            s.connect(("10.255.255.255", 1))
            return [s.getsockname()[0]]
    except OSError:
        return []


@web.route("GET", "/admin/status")
@_local
async def _status(request):
    version = paths.APP / "VERSION"
    return http.json_response({
        "name": settings.get("name") or "Jarvis", "computer": socket.gethostname().split(".")[0],
        "version": version.read_text().strip() if version.exists() else "development",
        "port": settings.get("port") or 8080, "addresses": _addresses(),
        "https_port": (settings.get("https_port") or 443) if kernel.enabled("https") else None,
        "bonjour": kernel.enabled("bonjour"), "pairing": kernel.enabled("pairing"),
        "devices": [{"device": s.device, "connected": s.pc.connectionState == "connected"}
                    for s in __import__("hub").all()]})


@web.route("GET", "/admin/qr")
@_local
async def _qr(request):
    import io

    import segno

    out = io.BytesIO()
    segno.make(request.query.get("text", ""), error="m").save(out, kind="svg", scale=6, border=2,
                                                              dark="#000", light="#fff")
    return http.Response(body=out.getvalue(), content_type="image/svg+xml")


@web.route("POST", "/admin/restart")
@_local
async def _restart(request):
    log.info("restart, from the admin page")
    web.stop(restart=True)
    return http.json_response({"restarting": True})


@web.route("POST", "/admin/stop")
@_local
async def _stop(request):
    log.info("stop, from the admin page or the app")
    web.stop()
    return http.json_response({"stopping": True})
