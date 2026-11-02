"""Controlling the Mac the server runs on by voice, without the LLM: «abre Safari» (also said
as it sounds: «abre crom»), «ejecuta el atajo Buenas noches», «abre la carpeta Descargas», «ve a
la ventana de Mail», «teclea hola» (with your «yes» first: it writes where the cursor is), and
«¿qué puedo decir?». And the same as tools for the LLM (open_app, run_shortcut, open_file,
go_to_window, type_text; list_apps, list_shortcuts).

The words and the matching are the plugin «control-language» (shared with the plugins for
other systems, to come); what touches the Mac is macos.py. Only clear commands: «abre X» is
taken only when an installed app answers to X, so «abre la puerta» or «¿me abres el correo?»
still go to the LLM. Typing is the one thing that changes something: it asks («¿Escribo
«hola»?») through the plugin «confirmation», as any action does.
"""

import asyncio
import logging
import threading
import time
from pathlib import Path

import i18n
import kernel
import options
import settings
from options import Option
from skills import Skill, skill
from tools import ToolError, tool

from plugins.control_language import commands, matching
from plugins.control_language.matching import Found, Window

from . import macos

log = logging.getLogger("control-mac")
options.add(Option("app_names", None, 'what you call an app, if it doesn\'t understand you: {"crome": "Google Chrome"}',
                   "skills", "dict", live=True, empty="none"))

FRESH = 300  # seconds the lists of apps and shortcuts are kept before looking again


class Cache:
    """A list that costs a command (the installed apps, the shortcuts): read the first time it is
    needed, kept a while, read again in the background when old, and at once when a name isn't
    found (something may have been installed since)."""

    def __init__(self, load):
        self.load = load
        self.items = None
        self.at = 0.0
        self.lock = threading.Lock()

    def get(self):
        if self.items is None:
            self.refresh()
        elif time.time() - self.at > FRESH:
            self.at = time.time()  # not twice
            threading.Thread(target=self.refresh, daemon=True).start()
        return self.items

    def refresh(self):
        with self.lock:
            self.items = self.load()
            self.at = time.time()
        return self.items


apps = Cache(lambda: macos.installed_apps())  # through the module: tests replace it
shortcuts = Cache(lambda: macos.shortcuts())


# --- Finding what was named ---

def _aliases() -> dict[str, str]:
    """What an app is called in this language («correo» → Mail, from the locale) and by you
    (settings «app_names»), spoken name → app name."""
    fillers = set(i18n.L.list("control.fillers"))

    def plain(alias: str) -> str:  # as it reaches the matching: «el bicho» is said «bicho»
        return " ".join(w for w in matching.normalise(alias).split() if w not in fillers)

    found = {plain(k): v for k, v in i18n.L.data.get("control_mac", {}).get("names", {}).items()}
    yours = settings.get("app_names") or {}
    if isinstance(yours, dict):
        found.update({plain(k): str(v) for k, v in yours.items()})
    return found


def find_app(name: str) -> macos.App | None:
    """The installed app a spoken name means: by its name, the one the Finder shows, or an alias."""
    spoken = matching.normalise(name).split()
    aliases = _aliases()
    for attempt in (apps.get, apps.refresh):
        candidates = []
        for app in attempt():
            names = [app.name, app.display] + [k for k, v in aliases.items() if v == app.name or v == app.display]
            candidates.append((app, names))
        found = matching.rank(spoken, candidates)
        if found:
            return found[0].item
    return None


def find_shortcut(name: str) -> str | None:
    spoken = matching.normalise(name).split()
    for attempt in (shortcuts.get, shortcuts.refresh):
        found = matching.rank_shortcuts(spoken, attempt())
        if found:
            return found[0]
    return None


def standard_folder(name: str) -> str | None:
    """«Descargas», «Desktop»: the standard folders answer by name, without Spotlight."""
    folders = i18n.L.data.get("control", {}).get("names", {}).get("folders", {})
    found = folders.get(matching.normalise(name))
    if not found:
        return None
    home = Path.home()
    if found == "~":
        path = home
    elif found == "/.Trash":
        path = home / ".Trash"
    elif found.startswith("/"):
        path = Path(found)
    else:
        path = home / found
    return str(path) if path.is_dir() else None


def find_file(name: str, folder: bool) -> list[Found]:
    """What answers to the name, best first: a standard folder outright (asked as a folder, or by
    its name alone); else Spotlight, ranked."""
    standard = standard_folder(name) if folder or len(name.split()) == 1 else None
    if standard:
        return [Found(standard, True)]
    words = matching.normalise(name).split()
    found = [Found(path, is_folder) for path, is_folder in macos.find_paths(words, folder)]
    return matching.rank_files(name, folder, found)


def where(path: str) -> str:
    """The folder a path is in, as said aloud («Documentos», «tu carpeta personal»)."""
    parent = Path(path).parent
    return i18n.L("speech.control_home") if parent == Path.home() else parent.name or str(parent)


def find_window(name: str) -> Window | None:
    spoken = matching.normalise(name).split()
    found = matching.rank_windows(spoken, [Window(w.app, w.title, w.pid) for w in macos.windows()])
    return found[0] if found else None


def _said_window(window: Window) -> str:
    return window.title.strip() or window.app


async def _in_thread(function, *args):
    """A macOS action off the loop (open may take a moment, the Accessibility API too)."""
    return await asyncio.get_running_loop().run_in_executor(None, function, *args)


# --- Typing, with your «yes» ---

async def _type(assistant, text: str):
    """«Teclea hola»: asks first (the plugin «confirmation», unless it is off or permissions.json
    says «confirm»: false), then types where the cursor is."""
    if not macos.trusted():
        assistant.say(i18n.L("speech.control_need_accessibility"))
        macos.ask_permission()
        return
    confirmation = kernel.module("confirmation")
    if confirmation and confirmation.asking():
        assistant.say(i18n.L("speech.control_type_ask", text=text))
        wait = settings.get("confirm_wait") or confirmation.store.WAIT
        started = time.time()
        sign = confirmation.store.signature("control-mac", "type", text)
        if not await confirmation.decision(sign, f"control-mac: type {text}"):
            if time.time() - started < wait - 1:  # answered, not dropped after the wait
                assistant.say(i18n.L("speech.control_type_cancelled"))
            return
    done = await _in_thread(macos.type_text, text)
    log.info("typed %d characters: %s", len(text), "ok" if done else "failed")
    assistant.say(i18n.L("speech.control_typed" if done else "speech.control_need_accessibility"))


# --- The skill ---

@skill
class ControlMac(Skill):
    order = 15  # after the language, the camera, the LLM and restarting; before timers and the clock
    local = False

    def hear(self, text: str, assistant) -> bool:
        command = commands.parse(text)
        if command is None:
            return False
        kind, name = command.kind, command.name
        if kind == "help":
            assistant.reply(text, commands.help_sentence())
            return True
        if kind == "type":
            assistant.show_heard(text)
            assistant.later(_type(assistant, name))
            return True
        if kind == "app":
            app = find_app(name)
            if app is None:
                return False  # not an app: the LLM's («abre la puerta»)
            log.info("opening %s", app.path)
            assistant.reply(text, i18n.L("speech.control_opening", name=app.display))
            assistant.later(_in_thread(macos.open_path, app.path))
            return True
        if kind == "shortcut":
            found = find_shortcut(name)
            if found:
                log.info("running the shortcut %s", found)
                macos.run_shortcut(found)
                assistant.reply(text, i18n.L("speech.control_shortcut", name=found))
            else:
                assistant.reply(text, i18n.L("speech.control_no_shortcut", name=name))
            return True
        if kind in ("file", "folder"):
            assistant.show_heard(text)
            assistant.later(self._open_file(assistant, name, kind == "folder"))
            return True
        if kind in ("window", "switch"):
            return self._switch(assistant, text, name, named_window=kind == "window")
        return False

    def _switch(self, assistant, text: str, name: str, named_window: bool) -> bool:
        """«Cambia a Safari»: an app by name (it comes forward, or opens), else a window by its
        title; nothing: the LLM's. «Ve a la ventana de Mail»: the window first, then the app; nothing
        answers to it: it says so (or that it can't see the windows without the permission)."""
        app = find_app(name)
        window = find_window(name) if macos.trusted() and (named_window or app is None) else None
        if window is not None and (named_window or app is None):
            log.info("going to the window «%s» of %s", window.title, window.app)
            assistant.reply(text, i18n.L("speech.control_window", name=_said_window(window)))
            assistant.later(_in_thread(macos.raise_window, macos.Window(window.app, window.title, window.pid)))
            return True
        if app is not None:
            log.info("switching to %s", app.path)
            assistant.reply(text, i18n.L("speech.control_window", name=app.display))
            assistant.later(_in_thread(macos.open_path, app.path))
            return True
        if not named_window:
            return False  # neither an app nor a window: the LLM's
        if not macos.trusted():
            assistant.reply(text, i18n.L("speech.control_need_accessibility"))
            macos.ask_permission()
        else:
            assistant.reply(text, i18n.L("speech.control_no_window", name=name))
        return True

    async def _open_file(self, assistant, name: str, folder: bool):
        found = await _in_thread(find_file, name, folder)
        if not found:
            assistant.say(i18n.L("speech.control_no_file", name=name))
            return
        best = found[0]
        log.info("opening %s", best.path)
        tied = len(found) > 1 and found[1].is_folder == best.is_folder and (
            matching.normalise(found[1].name) == matching.normalise(best.name))
        said = name.capitalize() if best.path == standard_folder(name) else best.name  # «Descargas», not Downloads
        if tied:  # two with the same name: which one is said, so a wrong guess is obvious at once
            assistant.say(i18n.L("speech.control_opening_in", name=said, where=where(best.path)))
        else:
            assistant.say(i18n.L("speech.control_opening", name=said))
        await _in_thread(macos.open_path, best.path)


# --- Tools for the LLM ---

@tool("The apps installed on the server (the Mac), to open one with open_app.")
def list_apps() -> str:
    return ", ".join(sorted({a.name for a in apps.get()}))


@tool("Open an app on the server (the Mac) by name, or bring it to the front if it is running.")
def open_app(name: str) -> str:
    app = find_app(name)
    if app is None:
        raise ToolError(f"no app called «{name}» (list_apps)")
    if not macos.open_path(app.path):
        raise ToolError(f"{app.name} couldn't be opened")
    return f"Opened {app.name}."


@tool("The Apple Shortcuts installed on the server, to run one with run_shortcut.")
def list_shortcuts() -> str:
    return ", ".join(shortcuts.get()) or "none"


@tool("Run an Apple Shortcut on the server by its name (list_shortcuts).", needs_yes=True)
def run_shortcut(name: str) -> str:
    found = find_shortcut(name)
    if found is None:
        raise ToolError(f"no shortcut called «{name}» (list_shortcuts)")
    if not macos.run_shortcut(found):
        raise ToolError(f"the shortcut {found} couldn't be started")
    return f"Running {found}."


@tool("Open a file or a folder of the user's by name on the server (Spotlight in their home folder; "
      "a standard folder by its name: Downloads, Desktop…).")
def open_file(name: str, folder: bool = False) -> str:
    found = find_file(name, folder)
    if not found:
        raise ToolError(f"nothing called «{name}» in the home folder")
    macos.open_path(found[0].path)
    others = f" (also: {', '.join(f.path for f in found[1:4])})" if len(found) > 1 else ""
    return f"Opened {found[0].path}.{others}"


@tool("Bring a window to the front on the server, by words of its title or its app's name.")
def go_to_window(name: str) -> str:
    if not macos.trusted():
        raise ToolError("the server lacks the Accessibility permission (System Settings → Privacy & Security → "
                        "Accessibility: the server's program)")
    window = find_window(name)
    if window is None:
        app = find_app(name)
        if app and macos.open_path(app.path):
            return f"Brought {app.name} to the front."
        raise ToolError(f"no window of «{name}»")
    macos.raise_window(macos.Window(window.app, window.title, window.pid))
    return f"Brought «{_said_window(window)}» ({window.app}) to the front."


@tool("Type text on the server where the keyboard focus is (a field, a document), as keystrokes.",
      needs_yes=True)
def type_text(text: str) -> str:
    if not macos.trusted():
        raise ToolError("the server lacks the Accessibility permission (System Settings → Privacy & Security → "
                        "Accessibility: the server's program)")
    if not macos.type_text(text):
        raise ToolError("nothing was typed")
    return f"Typed {len(text)} characters."
