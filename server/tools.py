"""Jarvis's own tools, for the LLM to manage itself (served over MCP by mcp_server.py).

Only what it may touch: face, voice, name, language, memory, the camera on the
screen, reloading its tools and restarting. Never the permissions, the
confirmation times, the port, the LLM or your instructions, so it cannot lift
its own safeguards. Tools that change something go through your «yes» like any
other (bin/jarvis-confirm), except showing the camera, which only changes the
screen.

Settings are saved to settings.json and applied after the answer (brain/assistant.py):
the face at once, voice, name and language with a restart. Reloading and
restarting also wait for the answer to end: doing it in the middle would cut
off the LLM while it is still using the tool.
"""

import re
import subprocess

import i18n
import memory
import settings

FACES = ["eyes", "orb"]
session = lambda: None  # noqa: E731 — the connected device's Session; set by main.py
requested: set[str] = set()  # «reload», «restart»: for when the answer ends


class ToolError(Exception):
    """A refusal or a wrong argument: its text goes back to the LLM."""


def voices() -> dict[str, str]:
    """{name: locale} of the Mac's voices, from `say -v ?`."""
    output = subprocess.run(["say", "-v", "?"], capture_output=True, text=True).stdout
    found = {}
    for line in output.splitlines():
        match = re.match(r"(.+?)\s+([a-z]{2}_[A-Z]{2})\s+#", line)
        if match:
            name = match.group(1).strip()
            found[name] = found[name.split(" (")[0]] = match.group(2)  # «Mónica (Español (España))» or «Mónica»
    return found


def get_status() -> str:
    device = session()
    camera = bool(device and device.frames)
    return (f"device connected: {'yes' if device else 'no'}; camera: {'yes' if camera else 'no'}; "
            f"language: {i18n.L.code}; LLM: {settings.get('llm')} ({settings.get('llm_model') or 'default'}); "
            f"eyes: {'on' if settings.get('eyes') else 'off'}; memory: {memory.mode()}")


def get_settings() -> str:
    return (f"name: {settings.get('name')}; face: {settings.get('face')}; "
            f"voice: {settings.get('voice') or 'the language default'}; language: {i18n.L.code} "
            f"(available: {', '.join(i18n.available())})")


def set_face(face: str) -> str:
    if face not in FACES:
        raise ToolError(f"face must be {' or '.join(FACES)}")
    settings.save(face=face)
    return "Saved: the face changes when you finish answering."


def set_voice(voice: str) -> str:
    found = voices()
    if voice not in found:
        raise ToolError(f"there is no voice «{voice}» on this Mac")
    if not found[voice].startswith(i18n.L.code):
        raise ToolError(f"«{voice}» speaks {found[voice]}, not {i18n.L.code}")
    current = settings.load().get("voice")
    current = current if isinstance(current, dict) else ({} if current is None else {i18n.L.code: current})
    settings.save(voice={**current, i18n.L.code: voice.split(" (")[0]})
    return "Saved: it restarts with the new voice when you finish answering."


def set_name(name: str) -> str:
    if not re.fullmatch(r"[^\W\d_]+( [^\W\d_]+)?", name.strip()):
        raise ToolError("a name is one or two words, letters only")
    settings.save(name=name.strip())
    return "Saved: it restarts with the new name (and wake word) when you finish answering."


def set_language(language: str) -> str:
    if language not in i18n.available():
        raise ToolError(f"available languages: {', '.join(i18n.available())}")
    settings.save(language=language)
    return "Saved: it restarts in that language when you finish answering."


def _memory_on():
    if memory.mode() == "off":
        raise ToolError("memory is off («memory» in settings.json)")


def get_memory() -> str:
    _memory_on()
    data = memory.load()
    text = "\n".join(f"{i}. {f}" for i, f in enumerate(data["facts"], 1)) or "(nothing yet)"
    if data["conversations"]:
        text += "\nRecent conversations:\n" + "\n".join(f"- {c['summary']}" for c in data["conversations"])
    return text


def remember(fact: str) -> str:
    _memory_on()
    data = memory.load()
    if fact.strip() and fact.strip() not in data["facts"]:
        data["facts"] = (data["facts"] + [fact.strip()])[-memory.MAX_FACTS:]
        memory.save(data)
    return "Remembered."


def forget(number: int) -> str:
    _memory_on()
    data = memory.load()
    if not 1 <= number <= len(data["facts"]):
        raise ToolError("give the number of a fact from get_memory")
    del data["facts"][number - 1]
    memory.save(data)
    return "Forgotten."


def camera(on: bool) -> str:
    device = session()
    if not device or not device.frames:
        raise ToolError("the device has no camera on")
    device.send({"type": "camera", "on": on})
    return "Shown on the screen." if on else "Hidden."


def reload_tools() -> str:
    requested.add("reload")
    return "It reloads its tools when you finish answering."


def restart() -> str:
    requested.add("restart")
    return "It restarts when you finish answering."


def _schema(**properties):
    return {"type": "object", "properties": properties, "required": list(properties)}


TOOLS = {
    "get_status": (get_status, "Whether the device and its camera are connected, the language, the LLM, eyes and memory.", _schema()),
    "get_settings": (get_settings, "Your name, face, voice and language.", _schema()),
    "set_face": (set_face, "The face on the screen.", _schema(face={"type": "string", "enum": FACES})),
    "set_voice": (set_voice, "Your voice in the current language: a macOS voice name (e.g. Mónica, Samantha).",
                  _schema(voice={"type": "string"})),
    "set_name": (set_name, "Your name, which is also your wake word («Hey …»).", _schema(name={"type": "string"})),
    "set_language": (set_language, "The language you speak and understand (a code such as en, es).",
                     _schema(language={"type": "string"})),
    "get_memory": (get_memory, "What you remember about the user (numbered) and recent conversations.", _schema()),
    "remember": (remember, "Keep a fact about the user for every conversation, when the user asks you to. "
                 "Short, in the third person, as they said it.", _schema(fact={"type": "string"})),
    "forget": (forget, "Forget a fact (its number from get_memory).", _schema(number={"type": "integer"})),
    "camera": (camera, "Show (true) or hide (false) the device's camera live on its screen.",
               _schema(on={"type": "boolean"})),
    "reload_tools": (reload_tools, "Read the MCP servers and permissions again (after the user authorized one).", _schema()),
    "restart": (restart, "Restart the whole server.", _schema()),
}


def call(name: str, arguments: dict) -> str:
    if name not in TOOLS:
        raise ToolError(f"unknown tool {name}")
    function = TOOLS[name][0]
    try:
        return function(**arguments)
    except TypeError as e:
        raise ToolError(f"wrong arguments: {e}") from None
