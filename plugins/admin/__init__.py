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
                           (in the active language: locale «options», «groups»); «voice» also
                           with the voice engine in use's voices in this language, to pick one
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
    """What settings.json says (or the default): what the field shows. A secret: never (only «set»)."""
    if option.kind == "secret":
        return None
    return _json(settings.load().get(option.name, option.default))


def _is_set(option) -> bool | None:
    """A secret: whether the keychain has it."""
    if option.kind != "secret":
        return None
    import keychain

    return bool(keychain.get(*option.keychain))


def _current(option):
    """What the server uses now: for an empty one, what it chose (the language's voice: «Mónica»;
    Kokoro's or Piper's own, ef_dora, where «Mónica» isn't one of theirs)."""
    value = settings.get(option.name, option.default)
    if option.name == "voice" and not value:
        import tts

        there = tts.voices()
        value = i18n.L.tts_voice if not there or i18n.L.tts_voice in there else there[0]
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
    if option.name == "llm":
        import llm

        return {str(c): llm.label(c) for c in found}
    return {str(c): i18n.L.text(f"choices.{option.name}.{c}", str(c)) for c in found}


def _voices(option) -> list | None:
    """«voice»: the voice engine in use's voices in this language, [{"name": "ef_dora", "label": "Dora",
    "language": "es"}…] (picking one sets that language's voice); None for the others, or with no engine."""
    if option.name != "voice":
        return None
    import tts

    engine = tts.engine()
    if not engine:
        return None
    try:
        return [{"name": v, "label": engine.label(v), "language": i18n.L.code} for v in tts.voices()]
    except Exception:  # a list that couldn't be made now
        log.exception("the voices of %s couldn't be listed", engine.name)
        return None


# The order they are shown in, within each section or plugin page: the most used first, the
# technical last. One not listed goes after these.
ORDER = ["name", "language", "llm", "llm_model", "instructions", "detail", "detail_levels", "ignore_others", "skills", "mcp", "voice", "rate", "volume", "wake_word", "threshold", "silence", "follow_up", "echo_guard", "voice_interrupt", "pause_when_microphone_busy", "listen_while_speaking", "tap_to_stop", "fillers", "stt", "stt_model", "stt_unload_minutes", "tts", "wake", "vad", "log_transcripts", "host", "port", "mode", "record", "conversations", "quiet_hours", "notices_where", "calendar_notice_minutes", "email_notice_query", "email_notice_says", "email_check_minutes", "confirm_wait", "confirm_valid", "read_photo", "https_port", "https_redirect_port", "interpreter", "llm_fallback", "openai_key", "openai_url", "memory", "memory_facts", "memory_conversations", "memory_days", "theme", "theme_options", "themes_dir", "show_time", "show_date", "show_hint", "show_status", "show_heard", "show_answer", "history", "show_timers", "clock", "video", "show_stats", "morning_after_alarm", "unread_query", "ring_seconds", "snooze_minutes", "alarm_rings", "location", "voice_check", "voice_adapt", "voice_match"]


def _order(option) -> int:
    return ORDER.index(option.name) if option.name in ORDER else len(ORDER)


@web.route("GET", "/admin/settings")
@_local
async def _settings(request):
    core = {o.group for o in options.OPTIONS if not o.plugin}  # the core's, by topic; a plugin's: on its page
    groups = [{"id": g, "title": i18n.L.text(f"groups.{g}", title)} for g, title in options.GROUPS.items()
              if g != "plugins" and g in core]
    found = [{"name": o.name, "group": o.group, "plugin": o.plugin, "kind": o.kind, "live": o.live,
              "title": _named(i18n.L.text(f"options_title.{o.name}", "")),
              "help": _named(i18n.L.text(f"options.{o.name}", o.help)), "default": _value_default(o),
              "value": _value(o), "current": None if o.kind == "secret" else _current(o), "set": _is_set(o), "choices": _choices(o), "labels": _labels(o),
              "empty": i18n.L.text(f"options_empty.{o.name}", o.empty) if o.empty else "",
              "voices": _voices(o)}
             for o in sorted(options.OPTIONS, key=_order) if o.group != "plugins" and not o.hidden]
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
    import keychain

    for key in [k for k in changes if options.BY_NAME[k].kind == "secret"]:  # to the keychain, not the file
        value = changes.pop(key)
        if value:
            keychain.put(*options.BY_NAME[key].keychain, str(value).strip())
        else:
            keychain.forget(*options.BY_NAME[key].keychain)
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
    """The server's addresses on the network, the one that reaches it first (the QR's, the one to
    type); self-assigned ones (169.254…, no router) last: other devices can't reach them."""
    routed = None
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
            s.connect(("10.255.255.255", 1))
            routed = s.getsockname()[0]
    except OSError:
        pass
    https = kernel.module("https")
    found = [a for a in (https.addresses() if https else []) if a != "127.0.0.1"]
    if routed and routed != "127.0.0.1":
        found = [routed] + [a for a in found if a != routed]
    return sorted(found, key=lambda a: (a != routed, a.startswith("169.254.")))


@web.route("GET", "/admin/status")
@_local
async def _status(request):
    """For «Conectar otro dispositivo» (the Mac app and the page here): what the QR says («connect»,
    the code goes after it), the addresses to type («local», and «address» for old devices), the
    certificate's if HTTPS is on, and whether a code is needed."""
    version = paths.APP / "VERSION"
    port = settings.get("port") or 8080
    addresses = _addresses()
    address = addresses[0] if addresses else "127.0.0.1"
    page = kernel.module("page")
    return http.json_response({
        "name": settings.get("name") or "Jarvis", "computer": socket.gethostname().split(".")[0],
        "version": version.read_text().strip() if version.exists() else "development",
        "port": port, "addresses": addresses, "address": address,
        "connect": page.connect_url(address, port) if page else None,
        "local": f"http://anyassistant.local:{port}",
        "certificate": f"http://{address}:{port}/https/ca.crt" if kernel.enabled("https") else None,
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
