"""Pairing (the plugin «pairing», off by default): only devices that entered a code may use Jarvis.

`bin/jarvis pair` asks the server (from the Mac itself) for a 6-digit code, valid
for a few minutes and a few attempts. The device that enters it gets a cookie
that it sends from then on; the server keeps only its hash, in paired.json.
The Mac itself never needs one. `bin/jarvis unpair` forgets every device.

It brings to the web server a guard (every protected request), its two routes and
«paired» in /config, so the page asks for the code; without the plugin, none exist.
"""

import hashlib
import json
import logging
import secrets
import time

from aiohttp import web as http

import paths
import settings
import installer
import web

FILE = paths.PAIRED
COOKIE = "jarvis_device"
CODE_LIFETIME = 300  # seconds
CODE_ATTEMPTS = 5
LOCAL = {"127.0.0.1", "::1"}
log = logging.getLogger("pairing")

_code: dict = {}  # {"code", "until", "attempts"}


def _hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def _moved():
    """Paired devices used to live in the cache folder (.build/paired.json): they are data."""
    old = paths.CACHE / "paired.json"
    if old.exists() and not FILE.exists():
        FILE.parent.mkdir(parents=True, exist_ok=True)
        old.rename(FILE)
        log.info("paired devices moved to %s", FILE)


def _devices() -> list[dict]:
    _moved()
    try:
        return json.loads(FILE.read_text())["devices"]
    except (OSError, ValueError, KeyError):
        return []


def allowed(remote: str | None, token: str | None) -> bool:
    """Whether a request may use Jarvis: from the Mac, or a paired device."""
    if remote in LOCAL:
        return True
    return bool(token) and any(d["hash"] == _hash(token) for d in _devices())


def new_code() -> str:
    global _code
    _code = {"code": f"{secrets.randbelow(10**6):06d}", "until": time.time() + CODE_LIFETIME,
             "attempts": CODE_ATTEMPTS}
    log.info("pairing code issued (valid %d s)", CODE_LIFETIME)
    return _code["code"]


def pair(code: str, name: str) -> str | None:
    """The device's token if the code is right; None otherwise (and the attempt counts)."""
    if not _code or time.time() > _code["until"] or _code["attempts"] <= 0:
        return None
    if not secrets.compare_digest(str(code).strip(), _code["code"]):
        _code["attempts"] -= 1
        return None
    _code.clear()  # one device per code
    token = secrets.token_urlsafe(32)
    devices = _devices() + [{"hash": _hash(token), "name": name[:120], "since": time.time()}]
    FILE.parent.mkdir(parents=True, exist_ok=True)
    FILE.write_text(json.dumps({"devices": devices}, indent=2))
    log.info("device paired: %s", name[:120])
    return token


def unpair_all():
    FILE.unlink(missing_ok=True)


# --- In the web server ---

@web.guard
def _guard(request):
    if not allowed(request.remote, request.cookies.get(COOKIE)):
        return http.json_response({"pairing": True}, status=403)
    return None


@web.config
def _config(request):
    return {"paired": allowed(request.remote, request.cookies.get(COOKIE))}


@web.route("POST", "/pairing")
async def _new_code(request):
    """For bin/jarvis pair: only from the Mac itself."""
    if request.remote not in LOCAL:
        return http.json_response({}, status=403)
    if request.query.get("forget"):
        unpair_all()
        return http.json_response({"forgotten": True})
    return http.json_response({"code": new_code(), "seconds": CODE_LIFETIME, "pairing": True})


@web.route("POST", "/pair")
async def _pair(request):
    data = await request.json()
    token = pair(data.get("code", ""), request.headers.get("User-Agent", "?"))
    if not token:
        return http.json_response({"paired": False}, status=403)
    response = http.json_response({"paired": True})
    response.set_cookie(COOKIE, token, max_age=10 * 365 * 24 * 3600, httponly=True, samesite="Strict")
    return response


# --- In the installer ---

@installer.question("pairing", "Only paired devices", order=60, choices=lambda: [True, False],
                    default=lambda: bool((settings.load().get("plugins") or {}).get("pairing", True)), always=True,
                    help="A device must type a code once before using it (the Mac never needs one).")
def _install(value):
    settings.save(plugins={**(settings.load().get("plugins") or {}), "pairing": bool(value)})
