"""Preferences: settings.json in the project, so nothing has to be typed when starting.

    {"language": "es", "name": "Jarvis", "llm": "claude", "voice": {"es": "Mónica", "en": "Daniel"},
     "instructions": ["I invoice with Holded."], "face": "orb"}

Keys are the server's options with underscores instead of dashes (language,
llm_model, echo_guard, idle_timeout…); options on the command line win. «voice»
can be one voice or one per language. Jarvis writes it too: «speak English»
saves the language here and restarts. $JARVIS_SETTINGS points elsewhere (tests).
"""

import json
import logging
import os
from pathlib import Path

# The options in effect (command line > settings.json > defaults), set by main.py.
active: dict = {}


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
