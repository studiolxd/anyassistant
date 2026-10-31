"""«Activa la cámara» / «apaga la cámara»: the device's camera live on its screen."""

import logging

import i18n
from skills import Skill, skill
from text import words
from tools import ToolError, tool

log = logging.getLogger("skills")


def command(text: str) -> str | None:
    """«Activa la cámara» → "on"; «Turn off the camera» → "off"."""
    heard = words(text)
    if not 0 < len(heard) <= 6 or not set(heard) & set(i18n.L.list("commands.camera")):
        return None
    if set(heard) & set(i18n.L.list("commands.camera_off")):  # before «on»: «turn off»
        return "off"
    if set(heard) & set(i18n.L.list("commands.camera_on")):
        return "on"
    return None


@skill
class Camera(Skill):
    order = 11
    local = False

    def hear(self, text, jarvis):
        found = command(text)
        if not found:
            return False
        on = found == "on"
        log.info("camera on the screen: %s", found)
        jarvis.show_heard(text)
        jarvis.send({"type": "camera", "on": on})
        jarvis.say(i18n.L("speech.camera_on" if on else "speech.camera_off"))
        return True


@tool("Show (true) or hide (false) the device's camera live on its screen.")
def camera(on: bool) -> str:
    import tools

    device = tools.session()
    if not device or not device.frames:
        raise ToolError("the device has no camera on")
    device.send({"type": "camera", "on": on})
    return "Shown on the screen." if on else "Hidden."
