"""The connected devices (several at once) and which one is talking to you now: who gets
screen messages, whose camera it sees, where alarms ring. Anyone can ask here instead of
being wired by main.py.

- Each device has its own connection (a transport.Session) and its own brain; a device
  that connects again replaces its old connection (`device`: the page's own id).
- A conversation per device (brain-assistant: an LLM each, up to «conversations»): the
  device that heard its name is the active one; with «conversations» 1, the others sleep.
- What a device's brain does, and the tools its LLM calls (the plugin mcp-server, by its
  ?device=), happen «here» (a context variable): current() is that device, not the last
  one woken somewhere else.
- When two devices hear the same «Jarvis» (they're near each other), only one answers:
  the one that heard it louder, within CLAIM_WINDOW seconds.
"""

import contextvars
import logging
import time

import settings

log = logging.getLogger("hub")

CLAIM_WINDOW = 1.5  # seconds: two devices hearing the same word (the wake word's own delays vary)

sessions: dict = {}  # id: transport.Session, in the order they connected
active = None  # the id of the session talking to you now (the last one woken)
_claim = None  # (session, level, at): the last wake-up by its name, to compare a second one
here = contextvars.ContextVar("here", default=None)  # the session this work is for (its audio, its LLM's tools)


def all() -> list:  # noqa: A001 (hub.all(): every connected device)
    return list(sessions.values())


def current():
    """The device this is for: «here» (its brain, its LLM's tools); else the one last woken; if
    none was woken yet, the last one connected."""
    session = here.get()
    if session is not None and sessions.get(session.id) is session:
        return session
    if active in sessions:
        return sessions[active]
    return next(reversed(sessions.values()), None)


def connected():
    """The current device, if its connection is up."""
    session = current()
    return session if session and session.pc.connectionState == "connected" else None


def by_device(device: str | None):
    """The connected session of a device (its page's id)."""
    return next((s for s in sessions.values() if device and s.device == device), None)


def of(brain):
    """The session of a brain (each device has its own)."""
    return next((s for s in sessions.values() if s.brain is brain), None)


def add(session) -> list:
    """A new connection; the old ones of the same device, to close (it reconnected)."""
    old = [s for s in sessions.values() if s.device and s.device == session.device]
    for s in old:
        sessions.pop(s.id, None)
    sessions[session.id] = session
    log.info("[%s] device %s connected (%d now)", session.id, session.device or "?", len(sessions))
    return old


def remove(session):
    global active
    if sessions.get(session.id) is session:
        del sessions[session.id]
        if active == session.id:
            active = None


def _awake(session) -> bool:
    ear = getattr(session.brain, "ear", None)
    return bool(ear and ear.wake and ear.awake)


def awake_elsewhere(brain) -> bool:
    """Whether another device is in a conversation (the LLM's is theirs: not to be reset)."""
    return any(_awake(s) for s in sessions.values() if s.brain is not brain)


def claim(brain, level: float = 0.0, why: str | None = None) -> bool:
    """A device wants to wake up: by its name (why None, `level` how loud it heard it), a tap…
    False if another one heard that same word better, or is the one speaking (its own voice
    saying its name, heard by a device nearby). If it may, it is the active one (and, with
    «conversations» 1, any other device in a conversation goes to sleep)."""
    global active, _claim
    session = of(brain)
    if session is None or why == "alarm":  # an alarm rings where it rings; it isn't a conversation
        return True
    now = time.time()
    others = [s for s in sessions.values() if s is not session]
    if why is None:
        if any(_speaking(s) for s in others):
            log.info("[%s] not woken: another device is speaking", session.id)
            return False
        hearing = [s for s in others if _awake(s) and s.brain.ear.speaking and s.brain.ear.level >= level]
        if hearing:  # you're talking to that one, which hears you better: it keeps the conversation
            log.info("[%s] not woken: [%s] is in a conversation and hears you better", session.id, hearing[0].id)
            return False
        if _claim and _claim[0] is not session and _claim[0].id in sessions and now - _claim[2] < CLAIM_WINDOW:
            if level <= _claim[1]:
                log.info("[%s] not woken: [%s] heard it louder (%.3f ≤ %.3f)", session.id, _claim[0].id,
                         level, _claim[1])
                return False
            log.info("[%s] heard it louder than [%s] (%.3f > %.3f): it answers", session.id, _claim[0].id,
                     level, _claim[1])
            _claim[0].brain.ear.drop("another device heard it louder")
        _claim = (session, level, now)
    active = session.id
    if (settings.get("conversations") or 2) <= 1:  # one conversation at a time: the others sleep
        for other in others:
            if _awake(other):
                other.brain.ear.sleep_for("another device woke up")
    return True


def _speaking(session) -> bool:
    ear = getattr(session.brain, "ear", None)
    return bool(ear and ear.deaf())


def send(message: dict) -> bool:
    """To the current device's page; False if there is none."""
    session = current()
    if session:
        session.send(message)
    return bool(session)


def broadcast(message: dict) -> int:
    """To every device's page; how many."""
    for session in sessions.values():
        session.send(message)
    return len(sessions)


def jpeg() -> bytes | None:
    """What the current device's camera sees now."""
    session = current()
    return session.jpeg() if session else None


def timers_changed():
    """The running timers changed: every page shows them."""
    for session in sessions.values():
        if hasattr(session.brain, "send_timers"):
            session.brain.send_timers()
