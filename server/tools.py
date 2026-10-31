"""Jarvis's own tools, for the LLM to manage itself (served over MCP by mcp_server.py).

Only what it may touch: skin, voice, name, language, memory, the camera on the
screen, which LLM it uses (among the installed ones), reloading its tools and
restarting. Never the permissions, the confirmation times, the port or your
instructions, so it cannot lift its own safeguards. Tools that change something go through your «yes» like any
other (bin/jarvis-confirm), except showing the camera, which only changes the
screen.

Settings are saved to settings.json and applied after the answer (brain/assistant.py):
the face at once, voice, name and language with a restart. Reloading and
restarting also wait for the answer to end: doing it in the middle would cut
off the LLM while it is still using the tool.
"""

import json
import platform
import re
import time
import shutil
import subprocess
import urllib.request

import confirmation
import i18n
import memory
import paths
import settings

session = lambda: None  # noqa: E731 — the connected device's Session; set by main.py
requested: set[str] = set()  # «reload», «restart»: for when the answer ends


# Tools that change something need the user's «yes», asked by the server itself, so
# it holds for any LLM using them (Claude, Hermes…), with the same mechanism as
# everyone else (confirmation.py).
NEEDS_YES = {"delete_skin", "set_voice", "set_name", "set_language", "remember", "update", "forget",
             "reload_tools", "restart", "set_llm", "add_detail_level", "remove_detail_level"}
ASK = ("This action changes data and needs the user's confirmation. Don't assume it: ask them in one "
       "short sentence whether to do it (say what you are going to do). If they answer yes, repeat "
       "exactly the same call; if not, don't do it.")


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
    import llm

    import skins

    return (f"name: {settings.get('name')}; skin: {settings.get('skin')} (skins: {', '.join(skins.available())}); "
            f"detail: {settings.get('detail') or 'neutral'} (levels: {', '.join(llm.detail_levels())}); "
            f"voice: {settings.get('voice') or 'the language default'}; language: {i18n.L.code} "
            f"(available: {', '.join(i18n.available())})")


def set_skin(skin: str, this_device: bool = False) -> str:
    import skins

    available = skins.available()
    if skin not in available:
        raise ToolError(f"skins: {', '.join(available)}")
    if this_device:
        device = session()
        if not device:
            raise ToolError("no device connected")
        device.send({"type": "skin", "name": skin})
        return "This device changes its skin now."
    settings.save(skin=skin)
    return "Saved: the skin changes when you finish answering."


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


# How each LLM is said aloud (and how speech recognition tends to write it).
LLM_NAMES = {"claude": ["claude", "claud", "clod", "cloud"], "apple": ["apple", "apel", "manzana"],
             "hermes": ["hermes"]}


def llm_ready(name: str) -> str | None:
    """None if the LLM can be used on this Mac; otherwise why not."""
    if name == "claude":
        return None if shutil.which("claude") else "Claude Code isn't installed"
    if name == "apple":
        major = int((platform.mac_ver()[0] or "0").split(".")[0])
        return None if major >= 26 else "it needs macOS 26 with Apple Intelligence"
    if name == "hermes":
        from llm.hermes import URL

        try:
            urllib.request.urlopen(URL + "/health", timeout=1)
            return None
        except OSError:
            return "Hermes's gateway isn't running"
    return None


def get_llms() -> str:
    import llm

    lines = []
    for name in llm.available():
        why = llm_ready(name)
        current = name == settings.get("llm")
        model = settings.get("llm_model") or "its default model"
        lines.append(f"{name}: " + ("in use, " + model + "; " if current else "")
                     + ("available" if why is None else f"not available ({why})"))
    return "\n".join(lines)


def set_llm(llm: str, model: str = "") -> str:
    import llm as plugins

    if llm not in plugins.available():
        raise ToolError(f"installed LLMs: {', '.join(plugins.available())}")
    why = llm_ready(llm)
    if why:
        raise ToolError(f"{llm} can't be used: {why}")
    if model and not re.fullmatch(r"[\w.\-\[\]:]+", model):
        raise ToolError("that isn't a model name")
    settings.save(llm=llm, llm_model=model or None)
    return f"Saved: it restarts with {llm} when you finish answering."


def set_detail(level: str) -> str:
    import llm

    if level not in llm.detail_levels():
        raise ToolError(f"levels: {', '.join(llm.detail_levels())}")
    settings.save(detail=level)
    return "Saved: from your next answer on."


def add_detail_level(name: str, instruction: str) -> str:
    import llm

    name, instruction = name.strip().lower(), instruction.strip()
    if not re.fullmatch(r"[^\W_][\w -]{0,29}", name):
        raise ToolError("a level's name is a word or two (up to 30 characters)")
    if not 10 <= len(instruction) <= 500:
        raise ToolError("the instruction must be a sentence or two (10 to 500 characters)")
    levels = settings.load().get("detail_levels") or {}
    settings.save(detail_levels={**levels, name: instruction})
    verb = "Changed" if name in llm.detail_levels() else "Added"
    return f"{verb}: the level «{name}». To use it: set_detail."


def remove_detail_level(name: str) -> str:
    import llm

    name = name.strip().lower()
    levels = settings.load().get("detail_levels") or {}
    if name not in levels:
        if name in llm.DETAIL_LEVELS:
            raise ToolError(f"«{name}» is built in and can't be removed")
        raise ToolError(f"no level «{name}»; levels: {', '.join(llm.detail_levels())}")
    del levels[name]
    changes = {"detail_levels": levels}
    if settings.get("detail") == name and name not in llm.DETAIL_LEVELS:
        changes["detail"] = "neutral"  # it was in use
    settings.save(**changes)
    if name in llm.DETAIL_LEVELS:
        return f"Removed your text for «{name}»: it is back to the built-in one."
    return "Removed." + (" Back to neutral." if "detail" in changes else "")


# Timers, alarms, reminders and volume: the same skills as by voice (skills/), for
# when the LLM is asked in its own words.

def set_timer(seconds: float, label: str = "") -> str:
    import skills

    if not 1 <= seconds <= 7 * 86400:
        raise ToolError("seconds: from 1 to a week")
    return skills.set_timer(seconds, label)


def _at(hour, minute, day, seconds) -> float:
    from skills import interpreter, parse

    if seconds:
        return time.time() + seconds
    if hour is None:
        raise ToolError("give seconds from now, or hour and minute")
    if day is None:
        return interpreter._next(int(hour) % 24, int(minute or 0))
    return parse.resolve(parse.Clock(int(hour) % 24, int(minute or 0), None, int(day)), waking=True)


def set_alarm(hour: int | None = None, minute: int = 0, day: int | None = None, seconds: float = 0) -> str:
    import skills

    return skills.set_alarm(_at(hour, minute, day, seconds))


def set_reminder(text: str, hour: int | None = None, minute: int = 0, day: int | None = None, seconds: float = 0) -> str:
    import skills

    if not text.strip():
        raise ToolError("what should it remind?")
    return skills.set_reminder(_at(hour, minute, day, seconds), text.strip())


def list_timers() -> str:
    import skills

    return skills.listing()


def cancel_timers(kind: str = "all") -> str:
    import skills

    return skills.cancel(kind if kind in ("timer", "alarm", "reminder") else None)


def set_volume(percent: int) -> str:
    import skills

    return skills.set_volume(percent)


# Skins of your own: create (a copy to start from), read, edit and delete; never the system's.

def create_skin(name: str, based_on: str = "eyes") -> str:
    import skins

    try:
        created = skins.new(name, based_on)
    except ValueError as e:
        raise ToolError(str(e)) from None
    return f"Created «{name}» from «{based_on}» in {created}. See it at /lab?skin={name}; set_skin to use it."


def get_skin(name: str) -> str:
    import skins

    try:
        found = skins.files(name)
    except ValueError as e:
        raise ToolError(str(e)) from None
    system = " (a system skin: copy it with create_skin to change it)" if skins.is_system(name) else ""
    return f"Skin «{name}»{system}:\n" + "\n\n".join(f"=== {file} ===\n{text}" for file, text in found.items())


def edit_skin(name: str, file: str, content: str) -> str:
    import skins

    try:
        problems = skins.write(name, file, content)
    except ValueError as e:
        raise ToolError(str(e)) from None
    device = session()
    if device and name in (settings.get("skin"), getattr(device.brain, "skin", None)):
        device.send({"type": "config"})  # the one on screen: it changes now
    if problems:
        return "Saved, but: " + "; ".join(problems)
    return "Saved. The check finds nothing wrong."


def delete_skin(name: str) -> str:
    import skins

    if name == settings.get("skin"):
        raise ToolError("it is the skin in use: choose another one first (set_skin)")
    try:
        skins.delete(name)
    except ValueError as e:
        raise ToolError(str(e)) from None
    return "Deleted."


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
        data["facts"] = (data["facts"] + [fact.strip()])[-memory.hard_limit():]  # compacted when it sleeps
        memory.save(data)
    return "Remembered."


def update(number: int, fact: str) -> str:
    _memory_on()
    data = memory.load()
    if not 1 <= number <= len(data["facts"]):
        raise ToolError("give the number of a fact from get_memory")
    if not fact.strip():
        raise ToolError("what should it say now?")
    data["facts"][number - 1] = fact.strip()
    memory.save(data)
    return "Updated."


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
    "set_skin": (set_skin, "The screen's look (a skin: eyes, orb… see get_settings), for every device or only "
                 "the one the user is talking to (this_device).",
                 {"type": "object", "properties": {"skin": {"type": "string"}, "this_device": {"type": "boolean"}},
                  "required": ["skin"]}),
    "set_voice": (set_voice, "Your voice in the current language: a macOS voice name (e.g. Mónica, Samantha).",
                  _schema(voice={"type": "string"})),
    "set_name": (set_name, "Your name, which is also your wake word («Hey …»).", _schema(name={"type": "string"})),
    "set_language": (set_language, "The language you speak and understand (a code such as en, es).",
                     _schema(language={"type": "string"})),
    "get_memory": (get_memory, "What you remember about the user (numbered) and recent conversations.", _schema()),
    "remember": (remember, "Keep a NEW fact about the user for every conversation, when the user asks you to. "
                 "Short, in the third person, as they said it. Call get_memory first: if a fact is about the "
                 "same thing (their name, a pet, a preference…), use update instead, never a second fact.",
                 _schema(fact={"type": "string"})),
    "update": (update, "Change a fact you remember (its number from get_memory) when the user corrects or "
               "changes it. Preferred over remember + forget: one step, one confirmation.",
               _schema(number={"type": "integer"}, fact={"type": "string"})),
    "forget": (forget, "Forget a fact (its number from get_memory).", _schema(number={"type": "integer"})),
    "camera": (camera, "Show (true) or hide (false) the device's camera live on its screen.",
               _schema(on={"type": "boolean"})),
    "set_detail": (set_detail, "How much you say in your answers: concise, neutral, detailed (or another level "
                   "from get_settings), when the user asks you to be briefer or to give more detail.",
                   _schema(level={"type": "string"})),
    "add_detail_level": (add_detail_level, "Create a detail level, or change one's instruction, when the user "
                         "asks for a new way of answering («a teacher mode that explains step by step»). The "
                         "instruction is added to your prompt: write it in English, one or two sentences, about "
                         "how much and how to answer (it is spoken: no lists). When asking for confirmation, "
                         "say it in the user's language.",
                         _schema(name={"type": "string"}, instruction={"type": "string"})),
    "remove_detail_level": (remove_detail_level, "Remove a detail level the user created (built-in ones go back "
                            "to their text).", _schema(name={"type": "string"})),
    "set_timer": (set_timer, "A timer: seconds from now, optionally with a label.",
                  {"type": "object", "properties": {"seconds": {"type": "number"}, "label": {"type": "string"}},
                   "required": ["seconds"]}),
    "set_alarm": (set_alarm, "An alarm at hour:minute (24 h; day 0 today, 1 tomorrow, 2 the day after; without "
                  "day, the next time it comes), or in some seconds.",
                  {"type": "object", "properties": {"hour": {"type": "integer"}, "minute": {"type": "integer"},
                                                    "day": {"type": "integer"}, "seconds": {"type": "number"}}}),
    "set_reminder": (set_reminder, "A reminder that says text aloud at hour:minute (24 h; day as for alarms) or "
                     "in some seconds.",
                     {"type": "object", "properties": {"text": {"type": "string"}, "hour": {"type": "integer"},
                                                       "minute": {"type": "integer"}, "day": {"type": "integer"},
                                                       "seconds": {"type": "number"}}, "required": ["text"]}),
    "list_timers": (list_timers, "The running timers, alarms and reminders.", _schema()),
    "cancel_timers": (cancel_timers, "Cancel the timers, alarms or reminders (kind), or all of them.",
                      {"type": "object", "properties": {"kind": {"type": "string",
                                                                 "enum": ["timer", "alarm", "reminder", "all"]}}}),
    "set_volume": (set_volume, "Its voice's volume, 5–100 %.", _schema(percent={"type": "integer"})),
    "create_skin": (create_skin, "Create a skin of the user's own as a copy of another (based_on: eyes, orb, "
                    "minimal, bedside or one of theirs), to customize it.",
                    {"type": "object", "properties": {"name": {"type": "string"}, "based_on": {"type": "string"}},
                     "required": ["name"]}),
    "get_skin": (get_skin, "Read a skin's files (skin.json, skin.html, skin.css, locales/*.json) before changing it.",
                 _schema(name={"type": "string"})),
    "edit_skin": (edit_skin, "Replace a whole file of one of the user's skins (not the system's): skin.json, "
                  "skin.html, skin.css or locales/<language>.json. HTML and CSS only, no JavaScript and nothing "
                  "from outside. skin.html places blocks Jarvis fills (data-block: face, status, heard, answer, "
                  "captions, clock, time, date, timers, photo, camera, stats); skin.css styles them by state with "
                  "body[data-look] (asleep, awake, hearing, thinking, looking, speaking, question, alarm, error), "
                  "body.blink and, on the face block, the live variables --voice, --speech, --bar-1…5 (0–1). "
                  "It runs on an old Chrome (81): no inset, no flex gap, no :has(). It answers what the check finds.",
                  _schema(name={"type": "string"}, file={"type": "string"}, content={"type": "string"})),
    "delete_skin": (delete_skin, "Delete one of the user's skins (never a system one).", _schema(name={"type": "string"})),
    "get_llms": (get_llms, "The LLMs Jarvis can use, which one is in use and whether each is available.", _schema()),
    "set_llm": (set_llm, "Switch to another LLM (claude, apple, hermes), optionally with a model (for Claude: "
                "sonnet, opus, haiku…; empty for the default). Apple's can't use tools: to come back, the user "
                "says «use Claude».", {"type": "object", "properties": {"llm": {"type": "string"},
                                                                      "model": {"type": "string"}},
                                       "required": ["llm"]}),
    "reload_tools": (reload_tools, "Read the MCP servers and permissions again (after the user authorized one).", _schema()),
    "restart": (restart, "Restart the whole server.", _schema()),
}


def confirmation_on() -> bool:
    try:
        permissions = json.loads(paths.PERMISSIONS.read_text())
    except (OSError, ValueError):
        permissions = {}
    return permissions.get("confirm", True) is not False


def confirmed(name: str, arguments: dict) -> bool:
    """Whether the user said «yes» to exactly this call (once); if not, it is left pending for them."""
    sign = confirmation.signature("jarvis", name, arguments)
    if confirmation.confirmed(sign):
        return True
    confirmation.ask(sign, f"jarvis: {name} {json.dumps(arguments, ensure_ascii=False)}")
    return False


def call(name: str, arguments: dict) -> str:
    if name not in TOOLS:
        raise ToolError(f"unknown tool {name}")
    if name in NEEDS_YES and confirmation_on() and not confirmed(name, arguments):
        raise ToolError(ASK)
    function = TOOLS[name][0]
    try:
        return function(**arguments)
    except TypeError as e:
        raise ToolError(f"wrong arguments: {e}") from None
