"""Skins: the look of the screen, made by anyone with HTML and CSS (no JavaScript).

A skin is a folder:

    skins/orb/
      skin.json        {"name": "Orb", "author": "…", "version": "1", "description": "…",
                        "options": {"accent": "#3ddc97"}}
      skin.html        the layout: where each block goes (<div data-block="clock"></div>…)
      skin.css         its styles and animations for each state
      locales/es.json  optional: {"ui": {…}} overrides the page's texts, {"skin": {…}} adds its own
      sounds/          optional: wake.wav, sleep.wav, alarm.wav
      preview.png      optional

System skins live in skins/; yours in «skins_dir» (paths.SKINS by default:
skins.local/ while developing, not in git). Jarvis fills the blocks; the skin
styles them with CSS, from body[data-state] / [data-look] and live CSS variables
(--voice, --speech, --bar-1…5). The skin's HTML is cleaned: no scripts, no on…
attributes, nothing loaded from outside (and the page forbids it too): the page
has the microphone and the camera.

    python server/skins.py check <folder>     problems for the tablet's old Chrome, and more
    python server/skins.py new <name> [--from orb]
"""

import json
import re
import shutil
import sys
import wave
from html.parser import HTMLParser
from pathlib import Path

import numpy as np

import paths

SYSTEM = paths.SYSTEM_SKINS
DEFAULT = "eyes"
BLOCKS = {"face", "status", "captions", "heard", "answer", "clock", "time", "date", "timers", "photo",
          "camera", "stats"}
SOUNDS = ("wake", "sleep", "alarm")
ASSETS = {".css", ".png", ".jpg", ".jpeg", ".gif", ".svg", ".webp", ".woff", ".woff2", ".ttf", ".otf",
          ".wav", ".mp3", ".ogg", ".json"}


def folders() -> list[Path]:
    import settings

    user = Path(settings.get("skins_dir") or paths.SKINS)
    return [SYSTEM, user if user.is_absolute() else paths.HOME / user]


def available() -> dict[str, Path]:
    """{name: folder}; yours win over system ones with the same name."""
    found = {}
    for base in folders():
        if base.is_dir():
            for folder in sorted(base.iterdir()):
                if (folder / "skin.json").exists():
                    found[folder.name] = folder
    return found


def folder(name: str) -> Path | None:
    return available().get(name)


def manifest(name: str) -> dict:
    path = folder(name)
    try:
        return json.loads((path / "skin.json").read_text()) if path else {}
    except ValueError:
        return {}


# --- Cleaning the skin's HTML ---

FORBIDDEN_TAGS = {"script", "iframe", "object", "embed", "link", "meta", "base", "form", "input", "button",
                  "textarea", "select", "frame", "frameset", "applet", "audio", "video", "source", "track"}
VOID = {"area", "br", "col", "hr", "img", "wbr"}


def _local(url: str) -> bool:
    """Only paths inside the skin («images/x.png»), never «http:», «//», «javascript:» or «data:»."""
    url = url.strip().lower()
    return not re.match(r"^([a-z][a-z0-9+.-]*:|//|/)", url) and ".." not in url


class _Cleaner(HTMLParser):
    def __init__(self, base: str):
        super().__init__(convert_charrefs=False)
        self.base, self.out, self.skip, self.removed = base, [], 0, []

    def handle_starttag(self, tag, attrs):
        if tag in FORBIDDEN_TAGS:
            self.removed.append(f"<{tag}>")
            if tag not in VOID and tag not in ("link", "meta", "base", "input", "source", "track", "embed"):
                self.skip += 1
            return
        if self.skip:
            return
        kept = []
        for name, value in attrs:
            value = value or ""
            if name.startswith("on"):
                self.removed.append(f"{name}=")
            elif name in ("src", "href", "srcset", "xlink:href", "poster", "background"):
                if _local(value):
                    kept.append((name, self.base + value))
                else:
                    self.removed.append(f"{name}={value[:40]}")
            elif name == "style" and re.search(r"url\s*\(|expression|javascript", value, re.I):
                self.removed.append("style with url()")
            else:
                kept.append((name, value))
        text = "".join(f' {n}="{_escape(v)}"' for n, v in kept)
        self.out.append(f"<{tag}{text}>")

    def handle_startendtag(self, tag, attrs):
        self.handle_starttag(tag, attrs)

    def handle_endtag(self, tag):
        if tag in FORBIDDEN_TAGS:
            if tag not in VOID and tag not in ("link", "meta", "base", "input", "source", "track", "embed"):
                self.skip = max(0, self.skip - 1)
            return
        if not self.skip and tag not in VOID:
            self.out.append(f"</{tag}>")

    def handle_data(self, data):
        if not self.skip:
            self.out.append(data)

    def handle_entityref(self, name):
        if not self.skip:
            self.out.append(f"&{name};")

    def handle_charref(self, name):
        if not self.skip:
            self.out.append(f"&#{name};")

    def handle_comment(self, data):
        pass


def _escape(value: str) -> str:
    return value.replace("&", "&amp;").replace('"', "&quot;").replace("<", "&lt;")


def clean(html: str, base: str = "") -> tuple[str, list[str]]:
    """The skin's HTML without anything that runs or loads from outside: (html, what was removed)."""
    cleaner = _Cleaner(base)
    cleaner.feed(html)
    cleaner.close()
    return "".join(cleaner.out), cleaner.removed


# --- What the page gets ---

def for_page(name: str, language: str) -> dict:
    """The skin for /config: its cleaned HTML, its stylesheet, texts and options."""
    path = folder(name) or folder(DEFAULT)
    name = path.name
    info = manifest(name)
    html, _ = clean((path / "skin.html").read_text(), base=f"/skin/{name}/")
    texts = {}
    for code in ("en", language):  # the skin's English, then its own language
        try:
            texts.update(json.loads((path / "locales" / f"{code}.json").read_text()))
        except (OSError, ValueError):
            pass
    import settings

    options = {**info.get("options", {}), **(settings.get("skin_options") or {})}
    return {"name": name, "title": info.get("name", name), "html": html, "css": f"/skin/{name}/skin.css",
            "version": int(max((p.stat().st_mtime for p in path.rglob("*") if p.is_file()), default=0)),
            "ui": texts.get("ui", {}), "texts": texts.get("skin", {}),
            "options": {k: str(v) for k, v in options.items() if re.fullmatch(r"[\w-]+", k)}}


def asset(name: str, path: str) -> Path | None:
    """A file of the skin, only inside its folder and of the allowed kinds."""
    base = folder(name)
    if not base:
        return None
    target = (base / path).resolve()
    if base.resolve() not in target.parents or target.suffix.lower() not in ASSETS or not target.is_file():
        return None
    return target


# --- Its sounds ---

_sounds: dict[tuple[str, float], np.ndarray | None] = {}


def sound(name: str, kind: str) -> np.ndarray | None:
    """The skin's sound (wake, sleep, alarm) as 48 kHz mono PCM, or None (the plugins' then)."""
    path = folder(name)
    file = path / "sounds" / f"{kind}.wav" if path else None
    if not file or not file.exists():
        return None
    return wav(file)


def wav(file: Path) -> np.ndarray | None:
    """A 16-bit WAV as 48 kHz mono PCM (kept while the file doesn't change), or None."""
    if not file.exists():
        return None
    key = (str(file), file.stat().st_mtime)
    if key not in _sounds:
        _sounds[key] = _read_wav(file)
    return _sounds[key]


def _read_wav(file: Path) -> np.ndarray | None:
    try:
        with wave.open(str(file)) as w:
            if w.getsampwidth() != 2:
                return None
            pcm = np.frombuffer(w.readframes(w.getnframes()), np.int16)
            if w.getnchannels() == 2:
                pcm = pcm.reshape(-1, 2).mean(axis=1).astype(np.int16)
            rate = w.getframerate()
        if rate != 48000:
            from scipy.signal import resample_poly
            from math import gcd

            g = gcd(48000, rate)
            pcm = resample_poly(pcm.astype(np.float32), 48000 // g, rate // g).astype(np.int16)
        return pcm[: 48000 * 10]  # at most 10 s
    except (OSError, wave.Error, EOFError):
        return None


# --- Checking a skin ---

OLD_CHROME = [  # the tablet's Chrome 81 doesn't have these
    (r"(^|[;{\s])inset\s*:", "«inset»: use top/right/bottom/left"),
    (r"(^|[;{\s])(row-)?gap\s*:", "«gap» doesn't work with flex in Chrome 81: use margins"),
    (r":has\(", "«:has()»"), (r":is\(", "«:is()»"), (r":where\(", "«:where()»"),
    (r"@container", "container queries"), (r"aspect-ratio\s*:", "«aspect-ratio» (Chrome 88)"),
    (r"@layer", "«@layer»"), (r"\bdvh\b|\bsvh\b|\blvh\b", "dvh/svh/lvh units"),
    (r"color-mix\(", "«color-mix()»"), (r"(^|[^-])\bnesting\b|&\s*[.:#]", "CSS nesting"),
]


def check(path: Path) -> list[str]:
    """What is wrong or won't work, in plain words; empty if it's fine."""
    problems = []
    for needed in ("skin.json", "skin.html", "skin.css"):
        if not (path / needed).exists():
            problems.append(f"missing {needed}")
    if problems:
        return problems
    try:
        info = json.loads((path / "skin.json").read_text())
        if not info.get("name"):
            problems.append("skin.json: no «name»")
    except ValueError as e:
        problems.append(f"skin.json isn't valid JSON: {e}")
    html = (path / "skin.html").read_text()
    _, removed = clean(html)
    problems += [f"skin.html: {r} is removed (no scripts, events or outside resources)" for r in removed]
    blocks = set(re.findall(r'data-block="([^"]+)"', html))
    problems += [f"skin.html: unknown block «{b}» (blocks: {', '.join(sorted(BLOCKS))})" for b in blocks - BLOCKS]
    if not blocks & {"status", "face"}:
        problems.append("skin.html: neither «face» nor «status»: nothing would show what it is doing")
    css = re.sub(r"/\*.*?\*/", "", (path / "skin.css").read_text(), flags=re.S)  # not in comments
    for pattern, why in OLD_CHROME:
        if re.search(pattern, css, re.M):
            problems.append(f"skin.css: {why}")
    if re.search(r"url\(\s*['\"]?(https?:|//)", css) or re.search(r"@import", css):
        problems.append("skin.css: outside resources (url(http…), @import) are blocked: put them in the skin's folder")
    for code_file in (path / "locales").glob("*.json") if (path / "locales").is_dir() else []:
        try:
            data = json.loads(code_file.read_text())
            extra = set(data) - {"ui", "skin"}
            if extra:
                problems.append(f"locales/{code_file.name}: only «ui» and «skin» count, not {', '.join(sorted(extra))}")
        except ValueError:
            problems.append(f"locales/{code_file.name} isn't valid JSON")
    for kind in SOUNDS:
        file = path / "sounds" / f"{kind}.wav"
        if file.exists() and _read_wav(file) is None:
            problems.append(f"sounds/{kind}.wav: it must be a 16-bit WAV")
    return problems


def new(name: str, source: str = DEFAULT) -> Path:
    """A copy of a skin to start from, in your skins folder."""
    if not re.fullmatch(r"[a-z0-9][a-z0-9_-]{0,30}", name):
        raise ValueError("a skin's name: lowercase letters, numbers, - and _")
    origin = folder(source)
    if not origin:
        raise ValueError(f"no skin «{source}»")
    target = folders()[1] / name
    if target.exists():
        raise ValueError(f"{target} already exists")
    shutil.copytree(origin, target)
    info = json.loads((target / "skin.json").read_text())
    info.update(name=name.capitalize(), based_on=source)
    (target / "skin.json").write_text(json.dumps(info, ensure_ascii=False, indent=2) + "\n")
    return target


# --- Yours, by voice (tools.py): create, read, edit, delete; never the system's ---

EDITABLE = re.compile(r"skin\.(json|html|css)|locales/[a-z]{2}\.json")
MAX_FILE = 100_000


def is_system(name: str) -> bool:
    path = folder(name)
    return bool(path) and path.parent.resolve() == SYSTEM.resolve()


def files(name: str) -> dict[str, str]:
    """The skin's text files, to read or change them."""
    path = folder(name)
    if not path:
        raise ValueError(f"no skin «{name}»")
    found = {f: (path / f).read_text() for f in ("skin.json", "skin.html", "skin.css") if (path / f).exists()}
    for locale in sorted((path / "locales").glob("*.json")) if (path / "locales").is_dir() else []:
        found[f"locales/{locale.name}"] = locale.read_text()
    return found


def write(name: str, file: str, content: str) -> list[str]:
    """Replaces a text file of one of your skins; returns what the check says about it."""
    path = folder(name)
    if not path:
        raise ValueError(f"no skin «{name}»")
    if is_system(name):
        raise ValueError(f"«{name}» is a system skin: make your own copy first (create_skin)")
    if not EDITABLE.fullmatch(file):
        raise ValueError("files: skin.json, skin.html, skin.css or locales/<language>.json")
    if len(content.encode()) > MAX_FILE:
        raise ValueError("too big: at most 100 KB per file")
    if file.endswith(".json"):
        json.loads(content)  # ValueError if it isn't JSON
    target = path / file
    target.parent.mkdir(exist_ok=True)
    target.write_text(content)
    return check(path)


def delete(name: str):
    path = folder(name)
    if not path:
        raise ValueError(f"no skin «{name}»")
    if is_system(name):
        raise ValueError(f"«{name}» is a system skin: it can't be deleted")
    shutil.rmtree(path)


# --- As tools, for the LLM (tools/) ---

def _tools():
    from tools import ToolError, tool

    def device():
        import tools

        return tools.session()

    @tool("The screen's look (a skin: eyes, orb… see get_settings), for every device or only the one the user is "
          "talking to (this_device).")
    def set_skin(skin: str, this_device: bool = False) -> str:
        import settings

        if skin not in available():
            raise ToolError(f"skins: {', '.join(available())}")
        if this_device:
            connected = device()
            if not connected:
                raise ToolError("no device connected")
            connected.send({"type": "skin", "name": skin})
            return "This device changes its skin now."
        settings.save(skin=skin)
        return "Saved: the skin changes when you finish answering."

    @tool("Create a skin of the user's own as a copy of another (based_on: eyes, orb, minimal, bedside or one of "
          "theirs), to customize it.")
    def create_skin(name: str, based_on: str = DEFAULT) -> str:
        try:
            created = new(name, based_on)
        except ValueError as e:
            raise ToolError(str(e)) from None
        return f"Created «{name}» from «{based_on}» in {created}. See it at /lab?skin={name}; set_skin to use it."

    @tool("Read a skin's files (skin.json, skin.html, skin.css, locales/*.json) before changing it.")
    def get_skin(name: str) -> str:
        try:
            found = files(name)
        except ValueError as e:
            raise ToolError(str(e)) from None
        system = " (a system skin: copy it with create_skin to change it)" if is_system(name) else ""
        return f"Skin «{name}»{system}:\n" + "\n\n".join(f"=== {file} ===\n{text}" for file, text in found.items())

    @tool("Replace a whole file of one of the user's skins (not the system's): skin.json, skin.html, skin.css or "
          "locales/<language>.json. HTML and CSS only, no JavaScript and nothing from outside. skin.html places "
          "blocks Jarvis fills (data-block: face, status, heard, answer, captions, clock, time, date, timers, photo, "
          "camera, stats); skin.css styles them by state with body[data-look] (asleep, awake, hearing, thinking, "
          "looking, speaking, question, alarm, error), body.blink and, on the face block, the live variables "
          "--voice, --speech, --bar-1…5 (0–1). It runs on an old Chrome (81): no inset, no flex gap, no :has(). "
          "It answers what the check finds.")
    def edit_skin(name: str, file: str, content: str) -> str:
        import settings

        try:
            problems = write(name, file, content)
        except ValueError as e:
            raise ToolError(str(e)) from None
        connected = device()
        if connected and name in (settings.get("skin"), getattr(connected.brain, "skin", None)):
            connected.send({"type": "config"})  # the one on screen: it changes now
        if problems:
            return "Saved, but: " + "; ".join(problems)
        return "Saved. The check finds nothing wrong."

    @tool("Delete one of the user's skins (never a system one).", needs_yes=True)
    def delete_skin(name: str) -> str:
        import settings

        if name == settings.get("skin"):
            raise ToolError("it is the skin in use: choose another one first (set_skin)")
        try:
            delete(name)
        except ValueError as e:
            raise ToolError(str(e)) from None
        return "Deleted."


if __name__ != "__main__":  # the command line below doesn't need the tools
    _tools()


if __name__ == "__main__":
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    import settings

    settings.active = settings.load()  # skins_dir
    args = sys.argv[1:]
    if args[:1] == ["check"] and len(args) == 2:
        found = check(Path(args[1]))
        print("\n".join(f"✗ {p}" for p in found) or "✓ The skin looks fine.")
        sys.exit(1 if found else 0)
    if args[:1] == ["new"] and len(args) >= 2:
        source = args[args.index("--from") + 1] if "--from" in args else DEFAULT
        print(f"Created {new(args[1], source)}: edit it and choose it with \"skin\": \"{args[1]}\".")
        sys.exit(0)
    if args[:1] == ["list"]:
        for name, path in available().items():
            print(f"{name:12} {manifest(name).get('description', '')}  ({path.parent.name}/)")
        sys.exit(0)
    print(__doc__.split("\n\n")[-1])
    sys.exit(2)
