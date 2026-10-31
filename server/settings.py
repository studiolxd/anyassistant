"""Preferences: settings.json in the project, so nothing has to be typed when starting.

    {"language": "es", "name": "Jarvis", "llm": "claude", "voice": {"es": "Mónica", "en": "Daniel"},
     "instructions": ["I invoice with Holded."], "face": "orb", "memory": "auto"}

Keys are the server's options with underscores instead of dashes (language,
llm_model, echo_guard, idle_timeout…); options on the command line win. «voice»
can be one voice or one per language. Jarvis writes it too (tools.py, «speak
English»), and the server applies it after each answer. $JARVIS_SETTINGS points elsewhere (tests).
"""

import json
import logging
import os
from pathlib import Path

# The options in effect (command line > settings.json > defaults), set by main.py.
active: dict = {}
fixed: set = set()  # the ones given on the command line: settings.json doesn't change them
# What can change without restarting (read again after every answer: its own tools,
# or settings.json edited by hand). Anything else restarts the server.
# What the page shows (sent to it in /config; it reads it again when one changes).
SCREEN = {"show_time", "show_date", "show_hint", "show_status", "show_heard", "show_answer", "history",
          "show_stats", "clock"}
LIVE = {"instructions", "face", "video", "confirm_wait", "confirm_valid", "log_transcripts", "eyes", "memory",
        "beeps", "fillers", "voice_interrupt", "tap_to_stop", "read_photo", "memory_facts",
        "memory_conversations", "memory_days"} | SCREEN


def get(key: str, default=None):
    return active.get(key, default)


PATH = Path(os.environ.get("JARVIS_SETTINGS") or Path(__file__).resolve().parent.parent / "settings.json")
log = logging.getLogger("settings")


def load() -> dict:
    try:
        return json.loads(PATH.read_text())
    except FileNotFoundError:
        return {}
    except ValueError as e:
        log.warning("settings.json is not valid JSON (%s): ignored", e)
        return {}


def save(**changes):
    """Changes some keys and keeps the rest (and the file's order)."""
    PATH.write_text(json.dumps({**load(), **changes}, ensure_ascii=False, indent=2) + "\n")


def private(text: str) -> str:
    """What was heard or said, for the log: only with log_transcripts; otherwise its length."""
    return text if active.get("log_transcripts") else f"[{len(text)} characters]"


def effective(key: str, value, language: str):
    """A settings.json value as the server uses it: the language's voice, instructions as text."""
    if key == "voice":
        return voice_for(value, language)
    if key == "instructions" and isinstance(value, list):
        return "\n".join(value)
    return value


def refresh() -> set[str]:
    """Reads settings.json again; returns the keys whose value changed (and applies the live ones)."""
    changed = set()
    language = active.get("language")
    for key, value in load().items():
        if key in active and key not in fixed:
            value = effective(key, value, language)
            if value != active[key]:
                changed.add(key)
                if key in LIVE:
                    active[key] = value
    if changed:
        log.info("settings.json changed: %s", ", ".join(sorted(changed)))
    return changed


def voice_for(voice, language: str) -> str | None:
    """«voice» as written in settings.json: one for all, or {language: voice}."""
    return voice.get(language) if isinstance(voice, dict) else voice


def without_option(argv: list[str], option: str) -> list[str]:
    """argv minus «--lang es» / «--lang=es»: so a restart honors settings.json's new value."""
    out, skip = [], False
    for arg in argv:
        if skip:
            skip = False
        elif arg == option:
            skip = True
        elif not arg.startswith(option + "="):
            out.append(arg)
    return out
