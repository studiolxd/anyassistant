"""What the plugin does to the Mac: the only module that touches it (tests replace these
functions). Subprocesses for what macOS gives as commands (Spotlight's mdfind, open, shortcuts),
and the system's own frameworks through ctypes for the rest (the windows and the keyboard:
the Accessibility API and CoreGraphics' events), so no Swift bridge and no package is needed.

The Accessibility API and posting keystrokes need the «Accessibility» permission for the
program that runs the server (trusted()); without it, events are silently dropped and no app
answers about its windows, so it is checked first and said aloud. ask_permission() makes
macOS show its dialog and list the program in System Settings.
"""

import ctypes
import logging
import subprocess
import sys
import time
from ctypes import POINTER, byref, c_bool, c_char_p, c_float, c_int32, c_int64, c_long, c_uint16, c_uint32, c_void_p
from dataclasses import dataclass
from pathlib import Path

log = logging.getLogger("control-mac")

TIMEOUT = 5  # seconds for a command (mdfind, shortcuts list)
APP_ROOTS = ("/Applications/", "/System/Applications/", str(Path.home() / "Applications") + "/")
FINDER = "/System/Library/CoreServices/Finder.app"


@dataclass
class App:
    name: str  # as installed: «Google Chrome»
    display: str  # as the Finder shows it, in the Mac's language: «Ajustes del Sistema»
    path: str


@dataclass
class Window:
    app: str
    title: str
    pid: int


def _run(args: list[str], timeout: float = TIMEOUT) -> str:
    """A command's output; empty if it failed or took too long."""
    try:
        done = subprocess.run(args, capture_output=True, text=True, timeout=timeout)
    except (OSError, subprocess.TimeoutExpired) as e:
        log.warning("%s: %s", args[0], e)
        return ""
    if done.returncode:
        log.info("%s failed: %s", args[0], done.stderr.strip()[-200:])
    return done.stdout


# --- Apps ---

def installed_apps() -> list[App]:
    """The apps in the Applications folders (the system's, yours), with the name the Finder shows."""
    output = _run(["mdfind", "-attr", "kMDItemDisplayName", "kMDItemContentType == 'com.apple.application-bundle'"])
    found = {}
    for line in output.splitlines():
        path, _, display = line.partition("   kMDItemDisplayName = ")
        path = path.strip()
        if not path.startswith(APP_ROOTS) or path.count(".app/") or not path.endswith(".app"):
            continue  # not an app of yours, or a helper inside another
        name = path.rsplit("/", 1)[-1][:-4]
        display = display.strip() or name
        found[path] = App(name, display[:-4] if display.endswith(".app") else display, path)
    found.setdefault(FINDER, App("Finder", "Finder", FINDER))
    return sorted(found.values(), key=lambda a: a.name)


def open_path(path: str) -> bool:
    """Opens an app, a file or a folder as a double click would (an app already running comes forward)."""
    done = subprocess.run(["open", path], capture_output=True, text=True)
    if done.returncode:
        log.warning("open %s: %s", path, done.stderr.strip())
    return done.returncode == 0


# --- Shortcuts ---

def shortcuts() -> list[str]:
    """The installed shortcuts' names (`shortcuts list`)."""
    return [line.strip() for line in _run(["shortcuts", "list"]).splitlines() if line.strip()]


def run_shortcut(name: str) -> bool:
    """Starts a shortcut without waiting for it (one may take a while, or ask something on screen)."""
    try:
        subprocess.Popen(["shortcuts", "run", name], stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                         stderr=subprocess.DEVNULL)
        return True
    except OSError as e:
        log.warning("shortcuts run: %s", e)
        return False


# --- Files ---

def spotlight_query(words: list[str], folder: bool) -> str:
    """One clause per spoken word, on the file's name and the name the Finder shows (a localized
    folder); «cd»: Spotlight's own «ignore case and accents»."""
    clauses = []
    for word in words:
        word = word.replace("\\", "").replace("'", "")
        clauses.append(f"(kMDItemFSName == '*{word}*'cd || kMDItemDisplayName == '*{word}*'cd)")
    if folder:
        clauses.append("kMDItemContentTypeTree == 'public.folder'")
    return " && ".join(clauses)


def find_paths(words: list[str], folder: bool) -> list[tuple[str, bool]]:
    """What Spotlight finds in your home folder for those words: (path, is a folder), unranked."""
    if not words:
        return []
    output = _run(["mdfind", "-onlyin", str(Path.home()), spotlight_query(words, folder)])
    found = []
    for path in output.splitlines()[:400]:
        path = path.strip()
        if path:
            found.append((path, Path(path).is_dir()))
    return found


# --- The Accessibility API and the keyboard (ctypes) ---

_libs: dict = {}
UTF8 = 0x08000100
AX_SUCCESS = 0
HID_TAP = 0


def _lib(name: str):
    if name not in _libs:
        _libs[name] = ctypes.cdll.LoadLibrary(f"/System/Library/Frameworks/{name}.framework/{name}")
        lib = _libs[name]
        if name == "CoreFoundation":
            lib.CFStringCreateWithCString.restype = c_void_p
            lib.CFStringCreateWithCString.argtypes = [c_void_p, c_char_p, c_uint32]
            lib.CFStringGetCString.restype = c_bool
            lib.CFStringGetCString.argtypes = [c_void_p, c_char_p, c_long, c_uint32]
            lib.CFStringGetLength.restype = c_long
            lib.CFStringGetLength.argtypes = [c_void_p]
            lib.CFGetTypeID.restype = c_long
            lib.CFGetTypeID.argtypes = [c_void_p]
            lib.CFStringGetTypeID.restype = c_long
            lib.CFArrayGetTypeID.restype = c_long
            lib.CFArrayGetCount.restype = c_long
            lib.CFArrayGetCount.argtypes = [c_void_p]
            lib.CFArrayGetValueAtIndex.restype = c_void_p
            lib.CFArrayGetValueAtIndex.argtypes = [c_void_p, c_long]
            lib.CFDictionaryGetValue.restype = c_void_p
            lib.CFDictionaryGetValue.argtypes = [c_void_p, c_void_p]
            lib.CFDictionaryCreate.restype = c_void_p
            lib.CFDictionaryCreate.argtypes = [c_void_p, POINTER(c_void_p), POINTER(c_void_p), c_long, c_void_p, c_void_p]
            lib.CFNumberGetValue.restype = c_bool
            lib.CFNumberGetValue.argtypes = [c_void_p, c_long, c_void_p]
            lib.CFRelease.argtypes = [c_void_p]
        elif name == "ApplicationServices":
            lib.AXIsProcessTrusted.restype = c_bool
            lib.AXIsProcessTrustedWithOptions.restype = c_bool
            lib.AXIsProcessTrustedWithOptions.argtypes = [c_void_p]
            lib.AXUIElementCreateApplication.restype = c_void_p
            lib.AXUIElementCreateApplication.argtypes = [c_int32]
            lib.AXUIElementCopyAttributeValue.restype = c_int32
            lib.AXUIElementCopyAttributeValue.argtypes = [c_void_p, c_void_p, POINTER(c_void_p)]
            lib.AXUIElementSetAttributeValue.restype = c_int32
            lib.AXUIElementSetAttributeValue.argtypes = [c_void_p, c_void_p, c_void_p]
            lib.AXUIElementPerformAction.restype = c_int32
            lib.AXUIElementPerformAction.argtypes = [c_void_p, c_void_p]
            lib.AXUIElementSetMessagingTimeout.restype = c_int32
            lib.AXUIElementSetMessagingTimeout.argtypes = [c_void_p, c_float]
        elif name == "CoreGraphics":
            lib.CGWindowListCopyWindowInfo.restype = c_void_p
            lib.CGWindowListCopyWindowInfo.argtypes = [c_uint32, c_uint32]
            lib.CGEventCreateKeyboardEvent.restype = c_void_p
            lib.CGEventCreateKeyboardEvent.argtypes = [c_void_p, c_uint16, c_bool]
            lib.CGEventKeyboardSetUnicodeString.argtypes = [c_void_p, c_long, POINTER(c_uint16)]
            lib.CGEventPost.argtypes = [c_uint32, c_void_p]
    return _libs[name]


def _cfstr(text: str) -> c_void_p:
    return c_void_p(_lib("CoreFoundation").CFStringCreateWithCString(None, text.encode(), UTF8))


def _pystr(ref) -> str:
    cf = _lib("CoreFoundation")
    if not ref or cf.CFGetTypeID(ref) != cf.CFStringGetTypeID():
        return ""
    size = cf.CFStringGetLength(ref) * 4 + 1
    buffer = ctypes.create_string_buffer(size)
    return buffer.value.decode("utf-8", "replace") if cf.CFStringGetCString(ref, buffer, size, UTF8) else ""


def _attribute(element, name: str):
    """An element's attribute (+1: release it), or None."""
    value = c_void_p()
    key = _cfstr(name)
    status = _lib("ApplicationServices").AXUIElementCopyAttributeValue(element, key, byref(value))
    _lib("CoreFoundation").CFRelease(key)
    return value if status == AX_SUCCESS and value.value else None


def _elements(array) -> list:
    cf = _lib("CoreFoundation")
    if not array or cf.CFGetTypeID(array) != cf.CFArrayGetTypeID():
        return []
    return [c_void_p(cf.CFArrayGetValueAtIndex(array, i)) for i in range(cf.CFArrayGetCount(array))]


def trusted() -> bool:
    """Whether macOS lets this program use the Accessibility API (see the windows, type)."""
    if sys.platform != "darwin":
        return False
    try:
        return bool(_lib("ApplicationServices").AXIsProcessTrusted())
    except (OSError, AttributeError) as e:
        log.warning("accessibility: %s", e)
        return False


def ask_permission():
    """Makes macOS show its dialog and list the program under Accessibility in System Settings."""
    try:
        cf, ax = _lib("CoreFoundation"), _lib("ApplicationServices")
        key = c_void_p.in_dll(ax, "kAXTrustedCheckOptionPrompt")
        yes = c_void_p.in_dll(cf, "kCFBooleanTrue")
        keys, values = (c_void_p * 1)(key.value), (c_void_p * 1)(yes.value)
        callbacks = ctypes.addressof(c_char_p.in_dll(cf, "kCFTypeDictionaryKeyCallBacks")), \
            ctypes.addressof(c_char_p.in_dll(cf, "kCFTypeDictionaryValueCallBacks"))
        options = cf.CFDictionaryCreate(None, keys, values, 1, c_void_p(callbacks[0]), c_void_p(callbacks[1]))
        ax.AXIsProcessTrustedWithOptions(options)
        cf.CFRelease(options)
    except (OSError, AttributeError, ValueError) as e:
        log.warning("accessibility prompt: %s", e)


def _apps_with_windows() -> list[tuple[int, str]]:
    """(pid, name) of the apps that have windows, front to back (CoreGraphics' window list; no
    permission needed for who owns them)."""
    cg, cf = _lib("CoreGraphics"), _lib("CoreFoundation")
    windows = cg.CGWindowListCopyWindowInfo(1 << 4, 0)  # every window but the desktop's elements
    found: list[tuple[int, str]] = []
    pid_key, name_key, layer_key = _cfstr("kCGWindowOwnerPID"), _cfstr("kCGWindowOwnerName"), _cfstr("kCGWindowLayer")
    for entry in _elements(windows):
        layer, pid = c_int64(), c_int64()
        layer_ref, pid_ref = cf.CFDictionaryGetValue(entry, layer_key), cf.CFDictionaryGetValue(entry, pid_key)
        if not layer_ref or not pid_ref:
            continue
        cf.CFNumberGetValue(layer_ref, 4, byref(layer))  # 4: kCFNumberSInt64Type
        cf.CFNumberGetValue(pid_ref, 4, byref(pid))
        name = _pystr(cf.CFDictionaryGetValue(entry, name_key))
        if layer.value == 0 and pid.value and (pid.value, name) not in found:
            found.append((pid.value, name))
    for ref in (pid_key, name_key, layer_key, windows):
        if ref:
            cf.CFRelease(ref)
    return found


def _app_windows(pid: int) -> tuple:
    """An app's accessibility element and its windows' elements (release the array afterwards)."""
    ax = _lib("ApplicationServices")
    app = c_void_p(ax.AXUIElementCreateApplication(pid))
    ax.AXUIElementSetMessagingTimeout(app, 0.5)  # an app that doesn't answer isn't waited for
    array = _attribute(app, "AXWindows")
    return app, array, _elements(array)


def windows() -> list[Window]:
    """Every window there is, with its app, front to back. Empty without the permission."""
    if not trusted():
        return []
    cf = _lib("CoreFoundation")
    found = []
    for pid, name in _apps_with_windows():
        app, array, elements = _app_windows(pid)
        for element in elements:
            title = _attribute(element, "AXTitle")
            found.append(Window(name, _pystr(title), pid))
            if title:
                cf.CFRelease(title)
        if array:
            cf.CFRelease(array)
        cf.CFRelease(app)
    return found


def raise_window(window: Window) -> bool:
    """Brings that window to the front, and its app with it."""
    if not trusted():
        return False
    cf, ax = _lib("CoreFoundation"), _lib("ApplicationServices")
    app, array, elements = _app_windows(window.pid)
    chosen = None
    for element in elements:
        title = _attribute(element, "AXTitle")
        same = _pystr(title) == window.title
        if title:
            cf.CFRelease(title)
        if same:
            chosen = element
            break
    done = False
    if chosen is not None:
        action = _cfstr("AXRaise")
        done = ax.AXUIElementPerformAction(chosen, action) == AX_SUCCESS
        cf.CFRelease(action)
    front = _cfstr("AXFrontmost")
    done = ax.AXUIElementSetAttributeValue(app, front, c_void_p.in_dll(cf, "kCFBooleanTrue")) == AX_SUCCESS or done
    cf.CFRelease(front)
    if array:
        cf.CFRelease(array)
    cf.CFRelease(app)
    return done


def type_text(text: str, chunk: int = 20) -> bool:
    """Types the text where the keyboard focus is, as keystrokes with the characters themselves (any
    language, any layout), a few at a time so no app drops any."""
    if not text or not trusted():
        return False
    cg, cf = _lib("CoreGraphics"), _lib("CoreFoundation")
    for start in range(0, len(text), chunk):
        piece = text[start:start + chunk].encode("utf-16-le")
        units = (c_uint16 * (len(piece) // 2)).from_buffer_copy(piece)
        for down in (True, False):
            event = c_void_p(cg.CGEventCreateKeyboardEvent(None, 0, down))
            if not event.value:
                return False
            cg.CGEventKeyboardSetUnicodeString(event, len(units), units)
            cg.CGEventPost(HID_TAP, event)
            cf.CFRelease(event)
        time.sleep(0.006)
    return True
