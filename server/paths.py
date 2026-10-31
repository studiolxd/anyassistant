"""Where everything lives: the program, your data and what can be thrown away.

    APP    the program (server/, web/, skins/, locales/, bin/): read-only once installed
    HOME   your data: settings.json, permissions.json, .mcp.json, memory.json,
           timers.json, paired.json, your skins, Google's client and token (.gog/)
    CACHE  what can be rebuilt: confirmations, the camera's image, the log, the
           compiled bridges…

$JARVIS_HOME and $JARVIS_CACHE choose them (the installer will); by default,
while developing, HOME is the project folder and CACHE its .build/, as always.
Plain Python 3.9 (bin/ scripts use it too).
"""

import os
from pathlib import Path

APP = Path(__file__).resolve().parent.parent
HOME = Path(os.environ.get("JARVIS_HOME") or APP)
CACHE = Path(os.environ.get("JARVIS_CACHE") or HOME / ".build")

# Your data
SETTINGS = HOME / "settings.json"
PERMISSIONS = HOME / "permissions.json"
MCP = HOME / ".mcp.json"
MEMORY = HOME / "memory.json"
TIMERS = HOME / "timers.json"
PAIRED = HOME / "paired.json"
SKINS = HOME / ("skins.local" if HOME == APP else "skins")  # yours; settings «skins_dir» may move them
GOOGLE_CLIENT = HOME / "google-client.json"
GOG = HOME / ".gog"

# The program
WEB = APP / "web"
LOCALES = APP / "locales"
SYSTEM_SKINS = APP / "skins"
BIN = APP / "bin"

# Can be rebuilt
CONFIRM = CACHE / "confirm"
EYES = CACHE / "eyes"
LOG = CACHE / "jarvis.log"


def environment() -> dict:
    """For the programs Jarvis starts (Claude, its hook, bin/gog): the same places."""
    return {"JARVIS_HOME": str(HOME), "JARVIS_CACHE": str(CACHE)}
