"""Themes: the look of the screen, made by anyone with HTML and CSS (no JavaScript).

A theme is a folder:

    themes/orb/
      theme.json        {"name": "Orb", "author": "…", "version": "1", "description": "…",
                        "options": {"accent": "#3ddc97"}}
      theme.html        the layout: where each block goes (<div data-block="clock"></div>…)
      theme.css         its styles and animations for each state
      locales/es.json  optional: {"ui": {…}} overrides the page's texts, {"theme": {…}} adds its own
                       ({"theme": {"description": …}}: its description in that language)
      sounds/          optional: wake.wav, sleep.wav, alarm.wav
      preview.png      optional

System themes live in plugins/page/themes/; yours in «themes_dir» (paths.THEMES by default:
themes.local/ while developing, not in git). Jarvis fills the blocks; the theme
styles them with CSS, from body[data-state] / [data-look] and live CSS variables
(--voice, --speech, --bar-1…5). The theme's HTML is cleaned: no scripts, no on…
attributes, nothing loaded from outside (and the page forbids it too): the page
has the microphone and the camera.

In the apps (iPhone, iPad, Android) the theme also says where their «Ajustes» button goes,
shown asleep or in error: options «settings» (bottom, top, bottom-left, bottom-right,
top-left, top-right; bottom if not said), «settings_style» (text or icon; text if not said)
and «settings_color» (else its «accent»).

    bin/anyassistant theme new <name> [--from orb]
"""

import json
import re
import shutil
import sys
from html.parser import HTMLParser
from pathlib import Path

import numpy as np

import audio
import paths

SYSTEM = Path(__file__).parent / "themes"  # the system's
DEFAULT = "eyes"
BLOCKS = {"face", "status", "captions", "heard", "answer", "clock", "time", "date", "timers", "photo",
          "camera", "stats"}
SOUNDS = ("wake", "sleep", "alarm")
ASSETS = {".css", ".png", ".jpg", ".jpeg", ".gif", ".svg", ".webp", ".woff", ".woff2", ".ttf", ".otf",
          ".wav", ".mp3", ".ogg", ".json"}


def folders() -> list[Path]:
    import settings

    user = Path(settings.get("themes_dir") or paths.THEMES)
    return [SYSTEM, user if user.is_absolute() else paths.HOME / user]


def part(path: Path, kind: str) -> Path:
    """The theme's theme.<kind> (json, html, css)."""
    return path / f"theme.{kind}"


def available() -> dict[str, Path]:
    """{name: folder}; yours win over system ones with the same name."""
    found = {}
    for base in folders():
        if base.is_dir():
            for folder in sorted(base.iterdir()):
                if part(folder, "json").exists():
                    found[folder.name] = folder
    return found


def folder(name: str) -> Path | None:
    return available().get(name)


def manifest(name: str) -> dict:
    path = folder(name)
    try:
        return json.loads(part(path, "json").read_text()) if path else {}
    except ValueError:
        return {}


def description(name: str, language: str) -> str:
    """Its description in that language: locales/<language>.json's {"theme": {"description"}}, else theme.json's."""
    path = folder(name)
    try:
        found = json.loads((path / "locales" / f"{language}.json").read_text())["theme"]["description"]
        if isinstance(found, str) and found:
            return found
    except (OSError, ValueError, KeyError, TypeError):
        pass
    return manifest(name).get("description", "")


# --- Cleaning the theme's HTML ---

FORBIDDEN_TAGS = {"script", "iframe", "object", "embed", "link", "meta", "base", "form", "input", "button",
                  "textarea", "select", "frame", "frameset", "applet", "audio", "video", "source", "track"}
VOID = {"area", "br", "col", "hr", "img", "wbr"}


def _local(url: str) -> bool:
    """Only paths inside the theme («images/x.png»), never «http:», «//», «javascript:» or «data:»."""
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
    """The theme's HTML without anything that runs or loads from outside: (html, what was removed)."""
    cleaner = _Cleaner(base)
    cleaner.feed(html)
    cleaner.close()
    return "".join(cleaner.out), cleaner.removed


# --- What the page gets ---

def for_page(name: str, language: str) -> dict:
    """The theme for /config: its cleaned HTML, its stylesheet, texts and options."""
    path = folder(name) or folder(DEFAULT)
    name = path.name
    info = manifest(name)
    html, _ = clean(part(path, "html").read_text(), base=f"/theme/{name}/")
    texts = {}
    for code in ("en", language):  # the theme's English, then its own language
        try:
            texts.update(json.loads((path / "locales" / f"{code}.json").read_text()))
        except (OSError, ValueError):
            pass
    import settings

    options = {**info.get("options", {}), **(settings.get("theme_options") or {})}
    return {"name": name, "title": info.get("name", name), "html": html, "css": f"/theme/{name}/theme.css",
            "version": int(max((p.stat().st_mtime for p in path.rglob("*") if p.is_file()), default=0)),
            "ui": texts.get("ui", {}), "texts": texts.get("theme", {}),
            "options": {k: str(v) for k, v in options.items() if re.fullmatch(r"[\w-]+", k)}}


def asset(name: str, path: str) -> Path | None:
    """A file of the theme, only inside its folder and of the allowed kinds."""
    base = folder(name)
    if not base:
        return None
    target = (base / path).resolve()
    if base.resolve() not in target.parents or target.suffix.lower() not in ASSETS or not target.is_file():
        return None
    return target


# --- Its sounds ---

def sound(name: str, kind: str) -> np.ndarray | None:
    """The theme's sound (wake, sleep, alarm) as 48 kHz mono PCM, or None (the plugins' then)."""
    path = folder(name)
    file = path / "sounds" / f"{kind}.wav" if path else None
    if not file or not file.exists():
        return None
    return audio.wav(file)




def check(path: Path) -> list[str]:
    """What is wrong in a theme, in plain words (missing files, unknown blocks, what gets removed): for
    the assistant when it edits one of yours; empty if it's fine."""
    problems = []
    for needed in ("json", "html", "css"):
        if not part(path, needed).exists():
            problems.append(f"missing theme.{needed}")
    if problems:
        return problems
    try:
        info = json.loads(part(path, "json").read_text())
        if not info.get("name"):
            problems.append("theme.json: no «name»")
    except ValueError as e:
        problems.append(f"theme.json isn't valid JSON: {e}")
    html = part(path, "html").read_text()
    _, removed = clean(html)
    problems += [f"theme.html: {r} is removed (no scripts, events or outside resources)" for r in removed]
    blocks = set(re.findall(r'data-block="([^"]+)"', html))
    problems += [f"theme.html: unknown block «{b}» (blocks: {', '.join(sorted(BLOCKS))})" for b in blocks - BLOCKS]
    if not blocks & {"status", "face"}:
        problems.append("theme.html: neither «face» nor «status»: nothing would show what it is doing")
    css = re.sub(r"/\*.*?\*/", "", part(path, "css").read_text(), flags=re.S)  # not in comments
    if re.search(r"url\(\s*['\"]?(https?:|//)", css) or re.search(r"@import", css):
        problems.append("theme.css: outside resources (url(http…), @import) are blocked: put them in the theme's folder")
    for code_file in (path / "locales").glob("*.json") if (path / "locales").is_dir() else []:
        try:
            data = json.loads(code_file.read_text())
            extra = set(data) - {"ui", "theme"}
            if extra:
                problems.append(f"locales/{code_file.name}: only «ui» and «theme» count, not {', '.join(sorted(extra))}")
        except ValueError:
            problems.append(f"locales/{code_file.name} isn't valid JSON")
    for kind in SOUNDS:
        file = path / "sounds" / f"{kind}.wav"
        if file.exists() and audio.wav(file) is None:
            problems.append(f"sounds/{kind}.wav: it must be a 16-bit WAV")
    return problems


def new(name: str, source: str = DEFAULT) -> Path:
    """A copy of a theme to start from, in your themes folder."""
    if not re.fullmatch(r"[a-z0-9][a-z0-9_-]{0,30}", name):
        raise ValueError("a theme's name: lowercase letters, numbers, - and _")
    origin = folder(source)
    if not origin:
        raise ValueError(f"no theme «{source}»")
    target = folders()[1] / name
    if target.exists():
        raise ValueError(f"{target} already exists")
    shutil.copytree(origin, target)
    info = json.loads(part(target, "json").read_text())
    info.update(name=name.capitalize(), based_on=source)
    part(target, "json").write_text(json.dumps(info, ensure_ascii=False, indent=2) + "\n")
    return target


# --- Yours, by voice (tools.py): create, read, edit, delete; never the system's ---

EDITABLE = re.compile(r"theme\.(json|html|css)|locales/[a-z]{2}\.json")
MAX_FILE = 100_000


def is_system(name: str) -> bool:
    path = folder(name)
    return bool(path) and path.parent.resolve() == SYSTEM.resolve()


def files(name: str) -> dict[str, str]:
    """The theme's text files, to read or change them."""
    path = folder(name)
    if not path:
        raise ValueError(f"no theme «{name}»")
    found = {f"theme.{kind}": part(path, kind).read_text() for kind in ("json", "html", "css") if part(path, kind).exists()}
    for locale in sorted((path / "locales").glob("*.json")) if (path / "locales").is_dir() else []:
        found[f"locales/{locale.name}"] = locale.read_text()
    return found


def write(name: str, file: str, content: str) -> list[str]:
    """Replaces a text file of one of your themes; returns what the check says about it."""
    path = folder(name)
    if not path:
        raise ValueError(f"no theme «{name}»")
    if is_system(name):
        raise ValueError(f"«{name}» is a system theme: make your own copy first (create_theme)")
    if not EDITABLE.fullmatch(file):
        raise ValueError("files: theme.json, theme.html, theme.css or locales/<language>.json")
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
        raise ValueError(f"no theme «{name}»")
    if is_system(name):
        raise ValueError(f"«{name}» is a system theme: it can't be deleted")
    shutil.rmtree(path)


# --- As tools, for the LLM (tools/) ---

def _tools():
    from tools import ToolError, tool

    def device():
        import tools

        return tools.session()

    @tool("The screen's look (a theme: eyes, orb… see get_settings), for every "
          "device or only the one the user is talking to (this_device).")
    def set_theme(theme: str, this_device: bool = False) -> str:
        import settings

        if theme not in available():
            raise ToolError(f"themes: {', '.join(available())}")
        if this_device:
            connected = device()
            if not connected:
                raise ToolError("no device connected")
            connected.send({"type": "theme", "name": theme})
            return "This device changes its theme now."
        settings.save(theme=theme)
        return "Saved: the theme changes when you finish answering."

    @tool("Create a theme of the user's own as a copy of another (based_on: eyes, orb, minimal, bedside or one of "
          "theirs), to change its look (colours, shapes, layout). Not to show or hide parts of the screen (the "
          "time, the transcription, the answers, the timers…): that is set_screen, for every theme.")
    def create_theme(name: str, based_on: str = DEFAULT) -> str:
        try:
            created = new(name, based_on)
        except ValueError as e:
            raise ToolError(str(e)) from None
        return f"Created «{name}» from «{based_on}» in {created}. See it at /themes?theme={name}; set_theme to use it."

    @tool("Read a theme's files (theme.json, theme.html, theme.css, locales/*.json) before changing it.")
    def get_theme(name: str) -> str:
        try:
            found = files(name)
        except ValueError as e:
            raise ToolError(str(e)) from None
        system = " (a system theme: copy it with create_theme to change it)" if is_system(name) else ""
        return f"Theme «{name}»{system}:\n" + "\n\n".join(f"=== {file} ===\n{text}" for file, text in found.items())

    @tool("Replace a whole file of one of the user's themes (not the system's): theme.json, theme.html, theme.css or "
          "locales/<language>.json. HTML and CSS only, no JavaScript and nothing from outside. theme.html places "
          "blocks Jarvis fills (data-block: face, status, heard, answer, captions, clock, time, date, timers, photo, "
          "camera, stats); theme.css styles them by state with body[data-look] (asleep, awake, hearing, thinking, "
          "looking, speaking, question, alarm, error), body.blink and, on the face block, the live variables "
          "--voice, --speech, --bar-1…5 (0–1). It answers what is wrong in it, if anything.")
    def edit_theme(name: str, file: str, content: str) -> str:
        import settings

        try:
            problems = write(name, file, content)
        except ValueError as e:
            raise ToolError(str(e)) from None
        connected = device()
        if connected and name in (settings.get("theme"), getattr(connected.brain, "theme", None)):
            connected.send({"type": "config"})  # the one on screen: it changes now
        if problems:
            return "Saved, but: " + "; ".join(problems)
        return "Saved. Nothing wrong in it."

    @tool("Delete one of the user's themes (never a system one).", needs_yes=True)
    def delete_theme(name: str) -> str:
        import settings

        if name == settings.get("theme"):
            raise ToolError("it is the theme in use: choose another one first (set_theme)")
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

    settings.active = settings.load()  # themes_dir
    args = sys.argv[1:]
    if args[:1] == ["new"] and len(args) >= 2:
        source = args[args.index("--from") + 1] if "--from" in args else DEFAULT
        print(f"Created {new(args[1], source)}: edit it and choose it with \"theme\": \"{args[1]}\".")
        sys.exit(0)
    if args[:1] == ["list"]:
        for name, path in available().items():
            print(f"{name:12} {manifest(name).get('description', '')}  ({path.parent.name}/)")
        sys.exit(0)
    print(__doc__.split("\n\n")[-1])
    sys.exit(2)
