"""Google, read without the LLM: the day's events and how many unread emails, for other
plugins (calendar-notices, morning). Through bin/gog (your account, under permissions.json's
policy: these are reads), with --json. None when gog can't answer (not authorized, no
network…): whoever asks says nothing about it.
"""

import datetime
import json
import logging
import subprocess
import time
from dataclasses import dataclass

import paths

log = logging.getLogger("google")
_failing = False  # said once in the log, not every time


@dataclass
class Event:
    id: str
    title: str
    start: float | None  # None: all day
    all_day: bool


def gog(*arguments: str) -> dict | None:
    """bin/gog's JSON answer, or None."""
    global _failing
    try:
        done = subprocess.run([str(paths.BIN / "gog"), *arguments, "--json"], capture_output=True, text=True,
                              timeout=30)
        if done.returncode != 0:
            raise RuntimeError((done.stderr or done.stdout).strip()[:300])
        found = json.loads(done.stdout)
    except (OSError, ValueError, RuntimeError, subprocess.SubprocessError) as e:
        if not _failing:
            log.warning("gog can't answer: %s", e)
        _failing = True
        return None
    _failing = False
    return found


def _event(raw: dict) -> Event | None:
    """One of Google's events; None if you said you won't go."""
    if any(a.get("self") and a.get("responseStatus") == "declined" for a in raw.get("attendees", ())):
        return None
    start = raw.get("start", {})
    title = (raw.get("summary") or "").strip()
    if "dateTime" in start:
        at = datetime.datetime.fromisoformat(start["dateTime"].replace("Z", "+00:00")).timestamp()
        return Event(raw.get("id", ""), title, at, False)
    return Event(raw.get("id", ""), title, None, True)


def events(day: int = 0, days: int = 1) -> list[Event] | None:
    """The events of `days` days from today + `day` (every calendar), in order; all-day ones first."""
    first = datetime.date.today() + datetime.timedelta(days=day)
    found = gog("calendar", "events", "--from", first.isoformat(), "--days", str(days), "--all")
    if found is None:
        return None
    every = [e for e in (_event(raw) for raw in found.get("events") or []) if e]
    return sorted(every, key=lambda e: (not e.all_day, e.start or 0))


def unread(query: str = "is:unread in:inbox", most: int = 100) -> tuple[int, bool] | None:
    """How many unread email threads (and whether there are more than `most`)."""
    found = gog("gmail", "search", query, "--max", str(most))
    if found is None:
        return None
    return int(found.get("count") or len(found.get("threads") or [])), bool(found.get("has_more"))


def today_left(now: float | None = None) -> tuple[list[Event], list[Event]] | None:
    """Today's all-day events, and its timed ones still to come."""
    found = events(0, 1)
    if found is None:
        return None
    now = now or time.time()
    return [e for e in found if e.all_day], [e for e in found if not e.all_day and e.start >= now - 60]
