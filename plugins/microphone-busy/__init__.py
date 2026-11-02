"""Another program is using this computer's microphone (a call in Teams or Zoom, a meeting in the
browser): the device of this computer's own app (the Windows and Linux app's page, connected from
127.0.0.1) is paused meanwhile (Ear.pause, why «microphone», the program's name) and resumed when
it ends; the page is told too («pause» / «resume»: its track sends silence). A browser page can't
know what else uses the microphone, so the server looks, once a second (settings
«pause_when_microphone_busy»):

- Windows (10 1903 or later): the registry's microphone consent store, what Windows itself reads
  for the microphone icon in the taskbar: a key per packaged app and, under NonPackaged, one per
  executable (its path with «#» for «\\»), each with LastUsedTimeStart and LastUsedTimeStop;
  LastUsedTimeStop == 0 means «in use now». No permission (HKCU). Our own app (Electron: its page
  keeps the microphone open) is left out by its name.
- Linux: PipeWire's `pw-dump` (the nodes with media.class Stream/Input/Audio in state running,
  with application.name and application.process.binary), or PulseAudio's `pactl list
  source-outputs` (the ones not corked; also when pw-dump is there but PipeWire doesn't answer). Our own Chromium is left out by its name or binary.
  Property names as documented, not verified on every distribution.

The condition has to hold a second before pausing and two before resuming (a change of a moment is
normal). Pure functions parse what each system gives, so tests can feed them samples.

The Windows and Linux app, as a client of another computer's server, does the same by itself
(apps/desktop/microphone.js, a port of these functions: a change here goes there too).
"""

import asyncio
import json
import logging
import re
import shutil
import subprocess
import sys
import time

import hub
import kernel
import settings
import web

log = logging.getLogger("microphone-busy")
EVERY = 1.0  # seconds between looks
BUSY_AFTER = 1.0  # seconds another program must have been recording before pausing
FREE_AFTER = 2.0  # seconds free before resuming
OURS = ("anyassistant",)  # our own app (the page's browser): its microphone is ours

CONSENT = r"Software\Microsoft\Windows\CurrentVersion\CapabilityAccessManager\ConsentStore\microphone"


def ours(name: str) -> bool:
    """Whether a program's name or path is our own app's."""
    return any(word in (name or "").lower() for word in OURS)


# --- Windows: the consent store ---

def windows_busy(entries: list[tuple[str, int, int]]) -> list[str]:
    """The names of the apps recording now, from (key name, LastUsedTimeStart, LastUsedTimeStop):
    started and not stopped. Our own left out."""
    found = []
    for name, start, stop in entries:
        if start and not stop and not ours(name):
            found.append(windows_name(name))
    return found


def windows_name(key: str) -> str:
    """A readable name: a packaged app's family name («Microsoft.Teams») or an executable's («Zoom»)."""
    leaf = key.replace("#", "\\").rsplit("\\", 1)[-1]
    if leaf.lower().endswith(".exe"):
        leaf = leaf[:-4]
    return leaf.split("_")[0] if "_" in leaf and not key.startswith("C:") else leaf


def windows_entries() -> list[tuple[str, int, int]]:
    """The consent store's keys as (name, start, stop): the packaged apps and the NonPackaged ones."""
    import winreg  # Windows only

    entries = []

    def read(path: str, prefix: str = ""):
        try:
            key = winreg.OpenKey(winreg.HKEY_CURRENT_USER, path)
        except OSError:
            return
        with key:
            for i in range(winreg.QueryInfoKey(key)[0]):
                name = winreg.EnumKey(key, i)
                if name == "NonPackaged":
                    read(path + r"\NonPackaged", "NonPackaged\\")
                    continue
                try:
                    with winreg.OpenKey(key, name) as sub:
                        start = _value(sub, "LastUsedTimeStart")
                        stop = _value(sub, "LastUsedTimeStop")
                except OSError:
                    continue
                entries.append((prefix + name, start, stop))

    def _value(sub, name: str) -> int:
        try:
            value, _ = winreg.QueryValueEx(sub, name)
            return int(value)
        except (OSError, ValueError, TypeError):
            return 0

    read(CONSENT)
    return entries


# --- Linux: PipeWire or PulseAudio ---

def pipewire_busy(dump: str) -> list[str]:
    """The apps recording now, from `pw-dump`'s JSON: input audio streams that are running."""
    try:
        nodes = json.loads(dump)
    except ValueError:
        return []
    found = []
    for node in nodes if isinstance(nodes, list) else []:
        info = node.get("info") or {}
        props = info.get("props") or {}
        if props.get("media.class") != "Stream/Input/Audio" or info.get("state") != "running":
            continue
        name = props.get("application.name") or props.get("node.name") or ""
        binary = props.get("application.process.binary") or ""
        if ours(name) or ours(binary):
            continue
        found.append(name or binary)
    return found


def pulse_busy(listing: str) -> list[str]:
    """The apps recording now, from `pactl list source-outputs`: the ones not corked."""
    found = []
    for block in re.split(r"(?m)^Source Output #", listing)[1:]:
        corked = re.search(r"(?m)^\s*Corked:\s*(\w+)", block)
        if corked and corked.group(1).lower() == "yes":
            continue
        name = re.search(r'application\.name = "([^"]*)"', block)
        binary = re.search(r'application\.process\.binary = "([^"]*)"', block)
        name, binary = name.group(1) if name else "", binary.group(1) if binary else ""
        if ours(name) or ours(binary):
            continue
        found.append(name or binary or "?")
    return found


def linux_busy() -> list[str]:
    for command, parse in (("pw-dump", pipewire_busy), ("pactl", pulse_busy)):
        if not shutil.which(command):
            continue
        args = [command] if command == "pw-dump" else [command, "list", "source-outputs"]
        try:
            done = subprocess.run(args, capture_output=True, text=True, timeout=3)
        except (OSError, subprocess.SubprocessError):
            continue
        if done.returncode != 0 and not done.stdout:  # there but not answering (PipeWire off): the next, as the app
            continue
        return parse(done.stdout)
    return []


def busy() -> list[str]:
    """The other programs recording now on this computer (their names)."""
    if sys.platform == "win32":
        return windows_busy(windows_entries())
    if sys.platform.startswith("linux"):
        return linux_busy()
    return []


# --- Watching, and the local devices ---

class Watch:
    """Busy a while before pausing, free a while before resuming: tick(found, now) says what
    changed: "busy" (with the program), "free", or None."""

    def __init__(self):
        self.busy = False
        self.since = None
        self.program = ""

    def tick(self, found: list[str], now: float) -> str | None:
        if bool(found) == self.busy:
            self.since = None
            return None
        self.since = self.since if self.since is not None else now
        if now - self.since < (FREE_AFTER if self.busy else BUSY_AFTER):
            return None
        self.busy, self.since = bool(found), None
        self.program = found[0] if found else ""
        return "busy" if self.busy else "free"


def local_sessions() -> list:
    """The devices connected from this computer itself (the app's page)."""
    return [s for s in hub.all() if getattr(s, "remote", "") in web.LOCAL and getattr(s.brain, "ear", None) is not None]


def apply(change: str, program: str):
    for session in local_sessions():
        if change == "busy":
            session.brain.ear.pause("microphone", program, source="server")
            session.send({"type": "pause"})
        else:
            session.brain.ear.resume("server")
            session.send({"type": "resume"})


watch = Watch()


async def _loop(app):
    """Once a second, while the plugin and the option are on."""
    while True:
        await asyncio.sleep(EVERY)
        try:
            if not kernel.enabled("microphone-busy") or settings.get("pause_when_microphone_busy", True) is False:
                if watch.busy:
                    apply(*(watch.tick([], time.time() + FREE_AFTER + 1) or "free", ""))
                continue
            if not local_sessions():
                continue
            found = await asyncio.get_running_loop().run_in_executor(None, busy)
            change = watch.tick(found, time.time())
            if change:
                log.info("microphone %s%s", change, f": {watch.program}" if watch.program else "")
                apply(change, watch.program)
        except Exception as e:  # noqa: BLE001 (it keeps looking)
            log.warning("%r", e)


@web.startup
async def _start(app):
    if sys.platform == "win32" or sys.platform.startswith("linux"):
        app["microphone-busy"] = asyncio.ensure_future(_loop(app))
