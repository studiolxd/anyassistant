"""The device connected now (one at a time): who gets screen messages, whose camera
it sees, where alarms ring. Anyone can ask here instead of being wired by main.py."""

sessions: dict = {}  # id: transport.Session (web.py keeps only the latest)


def current():
    return next(iter(sessions.values()), None)


def connected():
    """The device, if its connection is up."""
    session = current()
    return session if session and session.pc.connectionState == "connected" else None


def send(message: dict) -> bool:
    """To the device's page; False if there is none."""
    session = current()
    if session:
        session.send(message)
    return bool(session)


def jpeg() -> bytes | None:
    """What its camera sees now."""
    session = current()
    return session.jpeg() if session else None


def timers_changed():
    """The running timers changed: the page shows them."""
    session = current()
    if session and hasattr(session.brain, "send_timers"):
        session.brain.send_timers()
