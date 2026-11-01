"""Devices (the plugin «devices»): each device that connects (several at once: hub.py) has a
name and a room, kept in devices.json by the page's own id.

- A new device gets a name from what it is (iPad, iPhone, Android, Mac…); its room, nobody
  knows yet.
- The LLM changes them for the device you're talking to («this is the kitchen's», «call
  this one the bedside»), and sees which ones there are and which are connected.
- A message to another one («dile a la cocina que bajo ya»): said aloud there and shown on
  its screen, nothing more (tell_device).
- From the Mac itself, for the Mac app: GET /devices lists them; POST /devices {"id", "name",
  "room"} changes one, {"id", "forget": true} forgets it (it gets a new name if it comes back).
"""

import json
import logging
import re
import time

from aiohttp import web as http

import events
import hub
import paths
import settings
import tools
import web
from skills.tokens import tokens
from tools import ToolError, tool

FILE = paths.HOME / "devices.json"
log = logging.getLogger("devices")


def load() -> dict:
    """{device id: {"name", "room", "agent", "seen"}}."""
    try:
        return json.loads(FILE.read_text())["devices"]
    except (OSError, ValueError, KeyError):
        return {}


def _save(devices: dict):
    FILE.parent.mkdir(parents=True, exist_ok=True)
    FILE.write_text(json.dumps({"devices": devices}, indent=2, ensure_ascii=False))


def kind(agent: str) -> str:
    """What a browser's User-Agent says the device is."""
    for pattern, name in ((r"Watch", "Apple Watch"), (r"iPad", "iPad"), (r"iPhone", "iPhone"), (r"Android.*Mobile", "Android phone"),
                          (r"Android", "Android tablet"), (r"Macintosh|AnyAssistant Mac", "Mac"), (r"Windows|Linux|X11|CrOS", "PC")):
        if re.search(pattern, agent or ""):
            return name
    return "device"


def _unique(name: str, devices: dict, own: str) -> str:
    """«iPad», then «iPad 2»…: two devices of the same kind can be told apart."""
    taken = {d.get("name") for i, d in devices.items() if i != own}
    number, candidate = 1, name
    while candidate in taken:
        number += 1
        candidate = f"{name} {number}"
    return candidate


def llm_of(device: str | None) -> str | None:
    """The LLM a device uses if it has its own («usa Gemini aquí»); None: the general one."""
    return load().get(device or "", {}).get("llm") or None


def set_llm(device: str, name: str | None):
    """A device's own LLM (None or "": back to the general one). ToolError if it isn't known."""
    devices = load()
    if device not in devices:
        raise ToolError("no such device")
    if name:
        devices[device]["llm"] = name
    else:
        devices[device].pop("llm", None)
    _save(devices)
    log.info("%s: LLM %s", describe(device), name or "the general one")


def describe(device: str | None) -> str:
    """«iPad (living room)», for the logs and the LLM."""
    found = load().get(device or "", {})
    name = found.get("name") or "a device"
    return f"{name} ({found['room']})" if found.get("room") else name


@events.on("connected")
def _connected(session):
    if not session.device:
        return
    devices = load()
    found = devices.get(session.device)
    if found is None:
        found = devices[session.device] = {"name": _unique(kind(session.agent), devices, session.device), "room": ""}
        log.info("new device: %s", found["name"])
    known = found.get("seen")
    found.update(agent=(session.agent or "")[:200], seen=time.time())
    if getattr(session, "press_to_talk", False):
        found["press"] = True  # talks a sentence at a time (the watch): never «connected»
    _save(devices)
    if known is None or not found.get("press"):
        log.info("[%s] is %s", session.id, describe(session.device))


def matches(device: str | None, where: str) -> bool:
    """Whether that device is the room or the name «where» (as said: «Cocina», «la cocina»…)."""
    found = load().get(device or "", {})
    wanted = [t.plain for t in tokens(where)]
    for name in (found.get("room"), found.get("name")):
        if name:
            have = [t.plain for t in tokens(name)]
            if wanted == have or (len(wanted) > len(have) and wanted[-len(have):] == have):  # «la cocina»
                return True
    return False


def connected(where: str, but=None) -> list:
    """The connected devices that are «where» («all»: every one but `but`)."""
    found = [s for s in hub.all() if s.pc.connectionState == "connected" and s is not but]
    return found if where.strip().lower() == "all" else [s for s in found if matches(s.device, where)]


def through(session) -> str:
    """For the LLM, where the conversation is: «the device «iPad», in the room «dormitorio»»."""
    if not session or not session.device:
        return ""
    found = load().get(session.device, {})
    if not found:
        return ""
    room = f"in the room «{found['room']}»" if found.get("room") else "its room unknown"
    return f"the device «{found.get('name') or 'a device'}», {room}"


def _listing() -> list[dict]:
    connected = {s.device for s in hub.all() if s.pc.connectionState == "connected"}
    current = hub.current()
    return [{"id": i, "name": d.get("name", ""), "room": d.get("room", ""), "connected": i in connected,
             "current": bool(current and current.device == i), "seen": d.get("seen"),
             "press": bool(d.get("press")), "kind": kind(d.get("agent", "")), "llm": d.get("llm", "")}
            for i, d in load().items()]


def _llms() -> dict:
    """The LLMs a device may use, and the general one."""
    import llm

    return {"llms": llm.available(), "general": settings.get("llm") or "claude"}


# --- For the LLM ---

@tool("The devices you speak through: name, room, whether connected, and which one you're talking through now.")
def get_devices() -> str:
    found = _listing()
    if not found:
        return "no devices yet"
    return "; ".join(f"{d['name']}" + (f" in the {d['room']}" if d["room"] else ", room unknown")
                     + (", connected" if d["connected"] else
                        ", only while pressed to talk (it can't be told things)" if d["press"] else ", not connected")
                     + (" (you're talking through this one)" if d["current"] else "") for d in found)


def change(device: str, name: str | None = None, room: str | None = None, agent: str = ""):
    """A device's name and/or room (None: as it is; a room "" clears it). ToolError if the name is taken."""
    devices = load()
    found = devices.setdefault(device, {"name": _unique(kind(agent), devices, device), "room": ""})
    if name is not None and name.strip():
        name = name.strip()[:60]
        if any(d.get("name", "").lower() == name.lower() for i, d in devices.items() if i != device):
            raise ToolError(f"another device is already called «{name}»")
        found["name"] = name
    if room is not None:
        found["room"] = room.strip()[:60]
    _save(devices)
    log.info("%s is now %s", device, describe(device))


@tool("The name and/or room of the device you're talking through now (e.g. room «kitchen», name «tablet»). "
      "Use the user's words, in their language.")
def set_device(name: str = "", room: str = "") -> str:
    session = tools.session()
    if not session or not session.device:
        raise ToolError("no device is connected")
    if not name.strip() and not room.strip():
        raise ToolError("give a name or a room")
    change(session.device, name, room or None, session.agent)
    return f"this device is now {describe(session.device)}"


@tool("Say a message aloud on another device and show it on its screen, nothing more (not a reminder: "
      "no tone): «dile a la cocina que bajo ya». where: a room or a device's name (get_devices), or «all» for "
      "every other device. text: what is heard there, in the user's language, saying who sends it if it "
      "helps (e.g. «Desde el salón: bajo ya»).", name="tell_device")
def tell_device(where: str, text: str) -> str:
    text = text.strip()
    if not text:
        raise ToolError("what should it say?")
    here = tools.session()
    found = [s for s in connected(where, but=here) if hasattr(s.brain, "say")]
    if not found:
        raise ToolError(f"no other connected device is «{where}»; the devices: {get_devices()}")
    for session in found:
        session.brain.say(text)
    log.info("message to %s", ", ".join(describe(s.device) for s in found))
    return "said on " + ", ".join(describe(s.device) for s in found)


# --- For the Mac app ---

@web.route("GET", "/devices")
async def _devices(request):
    if not web.owner(request):  # this computer, or an admin's browser
        return http.json_response({}, status=403)
    return http.json_response({"devices": _listing(), **_llms()})


@web.route("POST", "/devices")
async def _change(request):
    if not web.owner(request):  # this computer, or an admin's browser
        return http.json_response({}, status=403)
    data = await request.json()
    device = str(data.get("id") or "")
    if device not in load():
        return http.json_response({"error": "no such device"}, status=404)
    if data.get("forget"):
        devices = load()
        devices.pop(device, None)
        _save(devices)
        log.info("%s forgotten", device)
    elif "llm" in data:  # its own LLM, or "" for the general one
        import llm

        if data["llm"] and data["llm"] not in llm.available():
            return http.json_response({"error": f"LLMs: {', '.join(llm.available())}"}, status=400)
        set_llm(device, data["llm"] or None)  # "": the default one (it follows it); a name: that one, fixed
    else:
        try:
            change(device, data.get("name"), data.get("room"))
        except ToolError as e:
            return http.json_response({"error": str(e)}, status=400)
    return http.json_response({"devices": _listing(), **_llms()})
