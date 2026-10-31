"""Eyes (the plugin «eyes», off by default): Jarvis sees through the device's camera.

Two ways, so it only looks when needed:
- A question with words like «see», «look», «read» (locale commands.look) carries
  the camera's image at that moment.
- For the rest («is my tie straight?»), Claude may open FRAME, the image at the
  moment of the question, with its Read tool: only that file (llm-claude/permissions.py).

To read («read this», «what does it say?»; locale commands.read) the video is
too small on some devices (320×240): the device takes a full-resolution photo
instead (photo()), and the video frame is used only if it doesn't arrive in time.

Nothing leaves the Mac unless it looks; only the latest image is kept, in .build/eyes.
It brings /eyes.jpg (the photo it looked at, for the screen) and /photo (where the
device sends the full-resolution one).
"""

import asyncio
import io
import itertools
import logging


from aiohttp import web as http

import hub
import installer
import i18n
import kernel
import options
import paths
import settings
import web
from options import Option
from text import words

log = logging.getLogger("eyes")
FRAME = paths.EYES / "now.jpg"
INSTRUCTIONS = """
You can see through the camera of the device the user talks to. When a question
comes with an image, that is what the camera sees right now. If one needs sight and
has no image, read {frame} with the Read tool: it is the camera's view at the moment
of the question. Describe only what matters, briefly, for speech. If there is no
image or no file, the camera isn't available: say so."""

source = hub.jpeg  # the connected device's camera, as JPEG
ask_device = hub.send  # a message to its page
PHOTO_WAIT = 4  # seconds for the device's photo
PHOTO_SIDE = 1568  # longest side sent to the LLM (more only costs time)
_waiting: dict[int, asyncio.Future] = {}
_ids = itertools.count(1)


options.add(Option("read_photo", True, "a full-resolution photo when asked to read", "assistant", "bool", live=True))


def enabled() -> bool:
    return kernel.enabled("eyes")


def wants_to_look(text: str) -> bool:
    return bool(set(words(text)) & set(i18n.L.list("commands.look")))


def wants_to_read(text: str) -> bool:
    return bool(set(words(text)) & set(i18n.L.list("commands.read")))


async def photo() -> bytes | None:
    """A full-resolution photo from the device, resized for the LLM; None if it doesn't come."""
    if not enabled():
        return None
    number = next(_ids)
    future = _waiting[number] = asyncio.get_running_loop().create_future()
    try:
        if not ask_device({"type": "photo", "id": number}):
            return None
        image = await asyncio.wait_for(future, PHOTO_WAIT)
    except asyncio.TimeoutError:
        return None
    finally:
        _waiting.pop(number, None)
    image = _resize(image)
    FRAME.parent.mkdir(parents=True, exist_ok=True)
    FRAME.write_bytes(image)
    return image


def photo_arrived(number: int, image: bytes, how: str = "?"):
    from PIL import Image

    try:
        size = "%d×%d" % Image.open(io.BytesIO(image)).size
    except Exception:
        size = "unreadable"
    log.info("photo from the device: %s (%s, %d KB)", size, how, len(image) // 1024)
    future = _waiting.get(number)
    if future and not future.done():
        future.set_result(image)


def _resize(image: bytes) -> bytes:
    from PIL import Image, ImageOps

    picture = ImageOps.exif_transpose(Image.open(io.BytesIO(image))).convert("RGB")
    picture.thumbnail((PHOTO_SIDE, PHOTO_SIDE))
    out = io.BytesIO()
    picture.save(out, format="JPEG", quality=85)
    return out.getvalue()


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


# --- In the web server ---

@web.route("GET", "/eyes.jpg")
async def _eyes_image(request):
    """The photo it just looked at, for the screen (paired devices only)."""
    if web.refused(request) or not FRAME.exists():
        return http.Response(status=404)
    return http.FileResponse(FRAME)


@web.route("POST", "/photo")
async def _photo(request):
    """The full-resolution photo the device took when asked to (photo())."""
    if refusal := web.refused(request):
        return refusal
    photo_arrived(int(request.query.get("id", 0)), await request.read(), request.query.get("how", "?"))
    return http.Response(status=204)


# --- In the installer ---

@installer.question("eyes", "Let it look through the device's camera", order=62, choices=lambda: [False, True],
                    default=lambda: bool((settings.load().get("plugins") or {}).get("eyes")), always=True,
                    help="Only when you ask («what do you see?», «read this»); nothing leaves the Mac otherwise.")
def _install(value):
    settings.save(plugins={**(settings.load().get("plugins") or {}), "eyes": bool(value)})
