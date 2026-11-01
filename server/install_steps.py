"""The core's own installer steps (installer.py): the computer, the packages, language,
name, LLM, the Swift bridges, the models, starting with the computer (launchd on the Mac,
systemd on Linux), and how to connect a device. The plugins add theirs (pairing, memory, eyes…).
"""

import importlib
import os
import platform
import plistlib
import shutil
import socket
import subprocess
import sys
import time
import urllib.request

import i18n
import kernel
import paths
import settings
from installer import Skip, question, task

APP_NAME = "AnyAssistant"
LABEL = "com.anyassistant.server"
AGENT = os.path.expanduser(f"~/Library/LaunchAgents/{LABEL}.plist")
UNIT = os.path.expanduser("~/.config/systemd/user/anyassistant.service")  # Linux


# --- The computer ---

@task("computer", "This computer", order=0)
def computer(progress):
    machine = platform.machine()
    if sys.platform.startswith("linux"):
        name = platform.freedesktop_os_release().get("PRETTY_NAME", "Linux") if hasattr(platform, "freedesktop_os_release") else "Linux"
        return f"{name}, {machine}"
    if sys.platform == "win32":
        return f"Windows {platform.release()} ({platform.version()}), {machine}"
    if sys.platform != "darwin":
        raise RuntimeError("it runs on macOS, Linux or Windows")
    version = platform.mac_ver()[0]
    note = "" if machine == "arm64" else " (Intel: speech recognition on MLX won't work)"
    return f"macOS {version}, {machine}{note}"


# --- The plugins' Python packages ---

def _uv() -> str:
    found = os.environ.get("UV") or shutil.which("uv") or os.path.expanduser("~/.local/bin/uv")
    if not os.path.exists(found):
        raise RuntimeError("uv isn't installed (install.sh installs it)")
    return found


@task("packages", "What the plugins need", order=20,
      help="The Python packages of the plugins that are on (bin/anyassistant plugins requirements).")
def packages(progress):
    if not paths.INSTALLED:
        raise Skip("while developing, uv sync installs them all")
    system = [p.id for p in kernel.discover().values() if not p.yours and kernel.python_needs(p)
              and kernel.wanted(p.id) and not [w for w in kernel.unfit(p.id) if not w.startswith("not installed")]]
    progress(None, "installing: " + (", ".join(system) or "only the core"))
    command = [_uv(), "sync", "--frozen", "--no-dev", *[a for p in system for a in ("--extra", p)]]
    subprocess.run(command, cwd=paths.APP, check=True, capture_output=True, text=True)
    yours = [r for p in kernel.discover().values() if p.yours and kernel.wanted(p.id)
             for r in kernel.python_needs(p)]
    if yours:
        progress(None, "your plugins: " + ", ".join(yours))
        subprocess.run([_uv(), "pip", "install", "--python", sys.executable, *yours], check=True,
                       capture_output=True, text=True)
    importlib.invalidate_caches()
    kernel._unfit.clear()  # what wasn't installed now is
    return f"{len(system)} plugins' packages" + (f", {len(yours)} of yours" if yours else "")


# --- Questions ---

@question("language", "Language", order=10, choices=lambda: i18n.available(), default=lambda: (
        settings.load().get("language") or i18n.detect()),
    help="The one it speaks and understands (you can change it later by voice).")
def language(value):
    settings.save(language=value)
    i18n.use(value)


@question("name", "The assistant's name", order=11, default=lambda: settings.load().get("name") or "Jarvis",
          help="Also its wake word: «Hey, …».")
def name(value):
    settings.save(name=str(value).strip() or "Jarvis")


def _llms():
    import llm

    found = []
    for name in llm.available():
        why = llm.ready(name)
        found.append({"value": name, "label": name if not why else f"{name} — {why}"})
    return found


def _llm_default():
    import llm

    chosen = settings.load().get("llm")
    if chosen and chosen in llm.available():
        return chosen
    ready = [n for n in ("claude", "apple", "hermes") if n in llm.available() and llm.ready(n) is None]
    return ready[0] if ready else "claude"


@question("llm", "Which LLM answers", order=30, choices=_llms, default=_llm_default,
          help="Claude needs Claude Code installed and signed in; Apple's, macOS 26 with Apple Intelligence.")
def choose_llm(value):
    import llm

    settings.save(llm=value)
    why = llm.ready(value)
    return f"{value}" + (f" (not ready yet: {why})" if why else "")


# --- What is built or downloaded ---

@task("bridges", "Swift bridges (Apple's model, the voice)", order=40, when=lambda: sys.platform == "darwin")
def bridges(progress):
    import swift

    built = []
    for name, source in swift.BRIDGES.items():
        if not kernel.wanted(_plugin_of(source)):
            continue
        progress(None, name)
        try:
            swift.build(source, name)
            built.append(name)
        except (OSError, RuntimeError) as e:
            raise RuntimeError(f"{name} couldn't be built (are Xcode's command line tools installed?): {e}")
    if not built:
        raise Skip("none needed")
    return ", ".join(built)


def _plugin_of(source) -> str:
    return source.parent.name


@task("models", "Speech models (they download once)", order=50,
      help="Speech recognition, the wake word and voice detection: a few hundred MB the first time.")
def models(progress):
    import stt
    import vad
    import wake

    chosen = {**{o: settings.load().get(o) for o in ("stt", "wake", "vad")}}
    import options

    kernel.load_all()
    options.resolve_defaults()
    defaults = {o.name: o.default for o in options.OPTIONS}
    done = []
    engine = stt.create(chosen["stt"] or defaults["stt"], language=i18n.L.stt_language)
    progress(None, f"speech recognition: {engine.name}")
    engine.warm_up()
    done.append(engine.name)
    wake_name = chosen["wake"] or defaults["wake"]
    if wake_name != "none":
        progress(None, f"wake word: {wake_name}")
        wake.create(wake_name, word=None)
        done.append(wake_name)
    progress(None, "voice detection")
    vad.create()
    done.append("vad")
    return ", ".join(done)


# --- Starting with the computer ---

def ours() -> bool:
    """Whether the launchd agent or systemd unit (if there is one) starts this copy: another
    copy's is left alone."""
    if sys.platform.startswith("linux"):
        try:
            with open(UNIT) as f:
                started = next(line for line in f if line.startswith("ExecStart=")).split("=", 1)[1].split()[0]
        except (OSError, StopIteration):
            return True  # none yet
        return os.path.realpath(started).startswith(os.path.realpath(paths.APP) + os.sep)
    try:
        with open(AGENT, "rb") as f:
            program = plistlib.load(f)["ProgramArguments"][0]
    except (OSError, KeyError, IndexError, plistlib.InvalidFileException):
        return True  # none yet
    return os.path.realpath(program).startswith(os.path.realpath(paths.APP) + os.sep)


def _launchctl(*args, check=True):
    return subprocess.run(["launchctl", *args], capture_output=True, text=True, check=check)


@question("service", f"Start {APP_NAME} with the computer", order=90, choices=lambda: [True, False],
          default=lambda: True, help="It runs in the background and comes back if it stops (launchd on the Mac, systemd on Linux).")
def service(value):
    if not paths.INSTALLED:
        raise Skip("only for an installed copy (install.sh); while developing, bin/anyassistant start")
    if not ours():
        raise Skip("another copy of AnyAssistant starts with the computer: left as it is")
    if sys.platform == "win32":
        raise Skip("on Windows, its app starts it")
    if sys.platform.startswith("linux"):
        return _systemd(value)
    if value and os.path.isdir("/Applications/AnyAssistant.app"):
        raise Skip("the AnyAssistant app starts it (open it at login: its menu)")
    domain = f"gui/{os.getuid()}"
    _launchctl("bootout", f"{domain}/{LABEL}", check=False)
    for _ in range(30):  # bootout returns before it is fully unloaded
        if _launchctl("print", f"{domain}/{LABEL}", check=False).returncode:
            break
        time.sleep(0.5)
    if not value:
        if os.path.exists(AGENT):
            os.remove(AGENT)
        return "off: start it with bin/anyassistant start"
    paths.CACHE.mkdir(parents=True, exist_ok=True)
    os.makedirs(os.path.dirname(AGENT), exist_ok=True)
    with open(AGENT, "wb") as f:
        plistlib.dump({
            "Label": LABEL,
            "ProgramArguments": [str(paths.BIN / "anyassistant"), "run"],
            "RunAtLoad": True,
            "KeepAlive": {"SuccessfulExit": False},  # back if it fails; not after «stop»
            "StandardOutPath": str(paths.LOG),
            "StandardErrorPath": str(paths.LOG),
            "EnvironmentVariables": {"PATH": "/usr/local/bin:/opt/homebrew/bin:/usr/bin:/bin:/usr/sbin:/sbin:"
                                             + os.path.expanduser("~/.local/bin")},
        }, f)
    for attempt in range(5):
        done = _launchctl("bootstrap", domain, AGENT, check=False)
        if done.returncode == 0:
            return "on: it starts with the Mac"
        time.sleep(1)
    raise RuntimeError(f"launchd didn't take it: {done.stderr.strip()}")


def _systemctl(*args, check=True):
    return subprocess.run(["systemctl", "--user", *args], capture_output=True, text=True, check=check)


def _systemd(value) -> str:
    """Linux: a systemd user unit (back if it fails; not after «stop»)."""
    if not shutil.which("systemctl"):
        raise Skip("no systemd here: start it with bin/anyassistant start")
    if not value:
        _systemctl("disable", "--now", "anyassistant", check=False)
        if os.path.exists(UNIT):
            os.remove(UNIT)
        _systemctl("daemon-reload", check=False)
        return "off: start it with bin/anyassistant start"
    paths.CACHE.mkdir(parents=True, exist_ok=True)
    os.makedirs(os.path.dirname(UNIT), exist_ok=True)
    with open(UNIT, "w") as f:
        f.write(f"""[Unit]
Description={APP_NAME}
After=network-online.target sound.target

[Service]
ExecStart={paths.BIN / "anyassistant"} run
Restart=on-failure
RestartSec=3
StandardOutput=append:{paths.LOG}
StandardError=append:{paths.LOG}
Environment=PATH=/usr/local/bin:/usr/bin:/bin:{os.path.expanduser("~/.local/bin")}

[Install]
WantedBy=default.target
""")
    _systemctl("daemon-reload")
    done = _systemctl("enable", "--now", "anyassistant", check=False)
    if done.returncode:
        raise RuntimeError(f"systemd didn't take it: {done.stderr.strip()}")
    # Without a session open (a server with no screen): `loginctl enable-linger` lets it start at boot.
    linger = subprocess.run(["loginctl", "show-user", os.environ.get("USER", ""), "-p", "Linger"],
                            capture_output=True, text=True).stdout.strip()
    note = "" if linger.endswith("yes") else " (at boot without logging in: sudo loginctl enable-linger $USER)"
    return "on: it starts with the computer" + note


# --- Connecting a device ---

def _address() -> str:
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
            s.connect(("10.255.255.255", 1))
            return s.getsockname()[0]
    except OSError:
        return "127.0.0.1"


@task("connect", "Connect your tablet or phone", order=100)
def connect(progress):
    port = settings.load().get("port", 8080)
    url = f"http://{_address()}:{port}"
    running = False
    if not (paths.INSTALLED and os.path.exists(AGENT) and ours()):  # whatever answers may be another copy
        return f"start it (bin/anyassistant start) and open {url} on the device"
    for _ in range(90):
        try:
            urllib.request.urlopen(f"http://127.0.0.1:{port}/status", timeout=1)
            running = True
            break
        except OSError:
            if not os.path.exists(AGENT):
                break
            progress(None, "waiting for it to start…")
            time.sleep(1)
    text = f"open {url} on the device"
    if running and kernel.enabled("pairing"):
        try:
            request = urllib.request.Request(f"http://127.0.0.1:{port}/pairing", data=b"", method="POST")
            code = __import__("json").load(urllib.request.urlopen(request, timeout=3))["code"]
            text += f" and type the code {code} (valid 5 minutes; bin/anyassistant pair for another)"
        except OSError:
            pass
    elif not running:
        text += " once it is running (bin/anyassistant start)"
    return text
