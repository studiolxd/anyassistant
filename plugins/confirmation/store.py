"""Your «yes» before actions that change something: one mechanism for everyone.

An action that needs it is left pending (pending.json: its signature, what it
is, when). When you answer, the plugin (its skill Answer, in __init__.py) either writes
confirmed.json with that signature, valid for a while and for one use, or
cancels it. Whoever asked (Jarvis's own tools, Claude Code's hook
bin/anyassistant-confirm, Hermes's approvals, Codex's…) checks it with confirmed(). Files in
paths.CONFIRM, so separate processes agree. Plain Python 3.9 (the hook uses it).
"""

import hashlib
import json
import time

import paths

WAIT = 120  # seconds to answer (settings «confirm_wait»)
# MCP tools named like these only read: they never wait for a «yes» (any other one does).
READS = ("get_", "list_", "search_", "find_", "preview_", "download_")
VALID = 60  # seconds a «yes» stays valid (settings «confirm_valid»)


def _file(name):
    return paths.CONFIRM / name


def _read(name):
    try:
        return json.loads(_file(name).read_text())
    except (OSError, ValueError):
        return None


def signature(*parts) -> str:
    """The same call always gets the same signature; any other, a different one."""
    return hashlib.sha256(json.dumps(list(parts), sort_keys=True).encode()).hexdigest()


def ask(sign: str, action: str, consume: bool = False):
    """Leaves an action waiting for the user's answer. consume: the answer is for whoever
    asked (Hermes's approvals), not a new message for the LLM."""
    paths.CONFIRM.mkdir(parents=True, exist_ok=True)
    _file("pending.json").write_text(json.dumps(
        {"signature": sign, "action": action, "at": time.time(), "consume": consume}, ensure_ascii=False))


def pending(wait: float = WAIT):
    """The action waiting for an answer, if it is recent enough; an old one is dropped."""
    found = _read("pending.json")
    if found and time.time() - found.get("at", 0) > wait:
        _file("pending.json").unlink(missing_ok=True)
        return None
    return found


def answer(yes: bool, valid: float = VALID):
    """The user answered the pending action: «yes» authorizes it once, for a while. Returns it."""
    found = _read("pending.json")
    if found and yes:
        _file("confirmed.json").write_text(json.dumps({"signature": found["signature"],
                                                       "until": time.time() + valid}))
    _file("pending.json").unlink(missing_ok=True)
    return found


def confirmed(sign: str) -> bool:
    """Whether the user said «yes» to exactly this (once: it is used up)."""
    found = _read("confirmed.json")
    if found and found.get("signature") == sign and found.get("until", 0) > time.time():
        _file("confirmed.json").unlink(missing_ok=True)
        return True
    return False


def waiting(sign: str) -> bool:
    """Whether this action is still waiting for an answer."""
    found = _read("pending.json")
    return bool(found) and found.get("signature") == sign
