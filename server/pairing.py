"""Pairing (settings «pairing»): only devices that entered a code may use Jarvis.

`bin/jarvis pair` asks the server (from the Mac itself) for a 6-digit code, valid
for a few minutes and a few attempts. The device that enters it gets a cookie
that it sends from then on; the server keeps only its hash, in .build/paired.json.
The Mac itself never needs one. `bin/jarvis unpair` forgets every device.
"""

import hashlib
import json
import logging
import os
import secrets
import time
from pathlib import Path

import settings

FILE = Path(os.environ.get("JARVIS_PAIRED") or Path(__file__).resolve().parent.parent / ".build" / "paired.json")
COOKIE = "jarvis_device"
CODE_LIFETIME = 300  # seconds
CODE_ATTEMPTS = 5
LOCAL = {"127.0.0.1", "::1"}
log = logging.getLogger("pairing")

_code: dict = {}  # {"code", "until", "attempts"}


def _hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def _devices() -> list[dict]:
    try:
        return json.loads(FILE.read_text())["devices"]
    except (OSError, ValueError, KeyError):
        return []


def allowed(remote: str | None, token: str | None) -> bool:
    """Whether a request may use Jarvis: always without pairing, from the Mac, or a paired device."""
    if not settings.get("pairing") or remote in LOCAL:
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
