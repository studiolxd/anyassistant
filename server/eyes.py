"""Eyes (settings «eyes», off by default): Jarvis sees through the device's camera, with Claude.

Two ways, so it only looks when needed:
- A question with words like «see», «look», «read» (locale commands.look) carries
  the camera's image at that moment.
- For the rest («is my tie straight?»), Claude may open FRAME, the image at the
  moment of the question, with its Read tool: only that file (llm/permissions.py).

Nothing leaves the Mac unless it looks; only the latest image is kept, in .build/eyes.
"""

from pathlib import Path

import i18n
import settings
from text import words

FRAME = Path(__file__).resolve().parent.parent / ".build" / "eyes" / "now.jpg"
INSTRUCTIONS = """
You can see through the camera of the device the user talks to. When a question
comes with an image, that is what the camera sees right now. If one needs sight and
has no image, read {frame} with the Read tool: it is the camera's view at the moment
of the question. Describe only what matters, briefly, for speech. If there is no
image or no file, the camera isn't available: say so."""

source = lambda: None  # noqa: E731 — the current device's camera as JPEG; set by main.py


def enabled() -> bool:
    return bool(settings.get("eyes"))


def wants_to_look(text: str) -> bool:
    return bool(set(words(text)) & set(i18n.L.list("commands.look")))


def capture() -> bytes | None:
    """The camera's image now, also left in FRAME for Claude's Read tool."""
    if not enabled():
        FRAME.unlink(missing_ok=True)
        return None
    image = source()
    if image:
        FRAME.parent.mkdir(parents=True, exist_ok=True)
        FRAME.write_bytes(image)
    else:
        FRAME.unlink(missing_ok=True)
    return image


def instructions() -> str:
    return INSTRUCTIONS.format(frame=FRAME) if enabled() else ""
