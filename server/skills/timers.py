"""Timers, alarms and reminders: kept in timers.json (not in git), so they survive a restart.

    [{"id": 3, "kind": "timer" | "alarm" | "reminder", "at": 1793…, "label": "call mom", "set": 1793…}]

The server checks them every half second (main.py) and rings the due ones on the
connected device (brain/assistant.py), or on the Mac if there is none.
"""

import json
import time

import hub
import paths

PATH = paths.TIMERS
KINDS = ("timer", "alarm", "reminder")
changed = hub.timers_changed  # the page shows them


def load() -> list[dict]:
    try:
        return json.loads(PATH.read_text())
    except (OSError, ValueError):
        return []


def save(items: list[dict]):
    PATH.write_text(json.dumps(items, ensure_ascii=False, indent=2) + "\n")
    changed()


def add(kind: str, at: float, label: str = "") -> dict:
    items = load()
    item = {"id": max([i["id"] for i in items], default=0) + 1, "kind": kind, "at": at, "label": label,
            "set": time.time()}
    save(sorted(items + [item], key=lambda i: i["at"]))
    return item


def pending(kind: str | None = None) -> list[dict]:
    return [i for i in load() if kind is None or i["kind"] == kind]


def cancel(kind: str | None = None) -> int:
    """Cancels those of a kind (or all): how many."""
    items = load()
    keep = [i for i in items if kind is not None and i["kind"] != kind]
    if len(keep) != len(items):
        save(keep)
    return len(items) - len(keep)


def due(now: float | None = None) -> list[dict]:
    """The ones whose time has come, taken out of the list."""
    now = now or time.time()
    items = load()
    ready = [i for i in items if i["at"] <= now]
    if ready:
        save([i for i in items if i["at"] > now])
    return ready
