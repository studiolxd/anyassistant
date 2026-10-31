"""The core: finds the plugins, loads them, and says which are on. Everything Jarvis
does is a plugin; this only puts them together.

A plugin is a folder (plugins/<id>/ in the app, or yours in paths.USER_PLUGINS:
one of yours with the same id replaces the system's) with:

    plugin.json    {"name": "Pairing", "description": "…", "kind": "feature",
                    "security": true, "requires": ["web-page"]}
    __init__.py    its code: it registers what it brings (@register, @skill, @tool,
                   events.on…, options.add…)
    locales/       optional: its texts per language, merged into Jarvis's
    …              anything else it needs (more modules, web files, a Swift bridge)

What it needs to be installed, in plugin.json «needs» (what the installer reads):

    "needs": {"python": ["parakeet-mlx>=0.5.3"],      packages (pip names)
              "system": ["darwin"], "arch": ["arm64"],  where it runs (sys.platform, the machine)
              "macos": 26,                              the oldest macOS
              "commands": ["claude"]}                   programs it calls (to install apart)

One that doesn't fit this computer or lacks its packages is off, whatever the settings
say (unfit() tells why); a missing command is only reported, as PATH may differ.

«kind» is what it is: brain (settings «mode» chooses one), stt, wake, llm, tts, vad (engines: the settings choose one),
skill, or feature. Every plugin found is loaded (importing one must be cheap:
heavy libraries only inside its classes); whether it is ON is checked when it is
used, from settings «plugins» ({"memory": false}) or its manifest's «default»
(true unless it says otherwise). So most can be turned on and off without
restarting. Plugins import each other as plugins.<id with underscores>.
"""

import importlib.metadata
import importlib.util
import json
import logging
import platform
import re
import shutil
import sys
import types
from dataclasses import dataclass, field
from pathlib import Path

import paths

log = logging.getLogger("kernel")
KINDS = ("brain", "stt", "wake", "llm", "tts", "vad", "skill", "feature", "library")


@dataclass
class Plugin:
    id: str
    folder: Path
    manifest: dict
    yours: bool = False
    module: object = field(default=None, repr=False)

    @property
    def kind(self) -> str:
        return self.manifest.get("kind", "feature")

    @property
    def security(self) -> bool:
        return bool(self.manifest.get("security"))

    @property
    def locked(self) -> bool:
        """Not turned off by voice (security ones, and what Jarvis can't work without: the page)."""
        return self.security or bool(self.manifest.get("locked"))

    @property
    def requires(self) -> list[str]:
        return list(self.manifest.get("requires", []))

    @property
    def needs(self) -> dict:
        return self.manifest.get("needs") or {}

    @property
    def module_name(self) -> str:
        return "plugins." + self.id.replace("-", "_")


_found: dict[str, Plugin] | None = None
loading: list[str] = []  # the plugin being imported now (what it registers is its)


def folders() -> list[Path]:
    return [paths.PLUGINS, paths.USER_PLUGINS]


def discover() -> dict[str, Plugin]:
    """Every plugin there is; yours replace the system's with the same id."""
    global _found
    if _found is None:
        _found = {}
        for base in folders():
            if not base.is_dir():
                continue
            for folder in sorted(base.iterdir()):
                manifest_file = folder / "plugin.json"
                if not manifest_file.exists():
                    continue
                try:
                    manifest = json.loads(manifest_file.read_text())
                except ValueError as e:
                    log.warning("%s: plugin.json isn't valid JSON (%s)", folder, e)
                    continue
                yours = base == paths.USER_PLUGINS
                if folder.name in _found and yours:
                    log.info("plugin %s: yours replaces the system's", folder.name)
                _found[folder.name] = Plugin(folder.name, folder, manifest, yours)
    return _found


def plugin(plugin_id: str) -> Plugin | None:
    return discover().get(plugin_id)


def choices() -> dict:
    """settings «plugins»: which are on or off by your choice."""
    import settings

    chosen = settings.get("plugins")
    if chosen is None:
        chosen = settings.load().get("plugins")  # before the settings are applied
    return chosen or {}


def _installed(requirement: str) -> bool:
    name = re.split(r"[<>=!~\[; ]", requirement, maxsplit=1)[0]
    try:
        importlib.metadata.version(name)
        return True
    except importlib.metadata.PackageNotFoundError:
        return False


_unfit: dict[str, list[str]] = {}


def unfit(plugin_id: str) -> list[str]:
    """Why a plugin can't work on this computer (another system, an older macOS, packages
    not installed); empty if it can."""
    if plugin_id not in _unfit:
        needs = plugin(plugin_id).needs if plugin(plugin_id) else {}
        why = []
        if needs.get("system") and sys.platform not in needs["system"]:
            why.append(f"only on {', '.join(needs['system'])}")
        if needs.get("arch") and platform.machine() not in needs["arch"]:
            why.append(f"only on {', '.join(needs['arch'])}")
        if needs.get("macos") and sys.platform == "darwin":
            major = int((platform.mac_ver()[0] or "0").split(".")[0])
            if major < int(needs["macos"]):
                why.append(f"macOS {needs['macos']} or later")
        missing = [r for r in needs.get("python", []) if not _installed(r)]
        if missing:
            why.append("not installed: " + ", ".join(missing))
        if why:
            log.info("plugin %s can't work here: %s", plugin_id, "; ".join(why))
        _unfit[plugin_id] = why
    return _unfit[plugin_id]


def commands_missing(plugin_id: str) -> list[str]:
    """The programs it calls that aren't on the PATH (only reported: it may differ when it runs)."""
    found = plugin(plugin_id)
    return [c for c in (found.needs.get("commands", []) if found else []) if not shutil.which(c)]


def enabled(plugin_id: str | None) -> bool:
    """Whether a plugin is on (and so are the ones it needs), and can work here. None: the core's own."""
    if plugin_id is None:
        return True
    found = plugin(plugin_id)
    if not found:
        return False
    on = choices().get(plugin_id, found.manifest.get("default", True))
    return bool(on) and not unfit(plugin_id) and all(enabled(r) for r in found.requires)


def wanted(plugin_id: str) -> bool:
    """On by the settings or its default (and the ones it needs), whether or not it is installed:
    what the installer has to install."""
    found = plugin(plugin_id)
    if not found:
        return False
    on = choices().get(plugin_id, found.manifest.get("default", True))
    return bool(on) and all(wanted(r) for r in found.requires)


def requirements(everything: bool = False) -> list[str]:
    """The Python packages of the plugins that are wanted (or of all) and fit this system."""
    found = []
    for p in discover().values():
        if not (everything or wanted(p.id)):
            continue
        fits = [w for w in unfit(p.id) if not w.startswith("not installed")]
        if not fits:
            found += [r for r in p.needs.get("python", []) if r not in found]
    return found


def _ensure_namespace():
    if "plugins" not in sys.modules:
        namespace = types.ModuleType("plugins")
        namespace.__path__ = []
        sys.modules["plugins"] = namespace


def load(plugin_id: str):
    """Imports a plugin (the ones it needs first); its module."""
    found = plugin(plugin_id)
    if not found:
        raise KeyError(f"no plugin «{plugin_id}»")
    if found.module is not None:
        return found.module
    for required in found.requires:
        load(required)
    _ensure_namespace()
    entry = found.folder / "__init__.py"
    spec = importlib.util.spec_from_file_location(found.module_name, entry,
                                                  submodule_search_locations=[str(found.folder)])
    module = importlib.util.module_from_spec(spec)
    sys.modules[found.module_name] = module
    found.module = module
    loading.append(plugin_id)
    try:
        spec.loader.exec_module(module)
    except Exception:
        sys.modules.pop(found.module_name, None)
        found.module = None
        raise
    finally:
        loading.pop()
    return module


def load_all(kind: str | None = None):
    """Imports every plugin found (of a kind): what they bring registers itself."""
    for plugin_id, found in discover().items():
        if kind is None or found.kind == kind:
            try:
                load(plugin_id)
            except Exception as e:  # one broken plugin mustn't stop Jarvis
                log.warning("plugin %s couldn't load: %r", plugin_id, e)


def current() -> str | None:
    """The plugin being loaded now (what registers itself belongs to it)."""
    return loading[-1] if loading else None


def module(plugin_id: str):
    """Another plugin's module (loading it if needed), or None if it isn't there or is off."""
    if not enabled(plugin_id):
        return None
    return load(plugin_id)


def describe() -> list[dict]:
    return [{"id": p.id, "name": p.manifest.get("name", p.id), "kind": p.kind,
             "description": p.manifest.get("description", ""), "on": enabled(p.id), "security": p.security,
             "yours": p.yours, "requires": p.requires, "unfit": unfit(p.id),
             "commands_missing": commands_missing(p.id)} for p in discover().values()]


def locale_files(code: str) -> list[Path]:
    """The plugins' texts for a language: every plugin's, on or off (an off plugin is still listed
    in the app's settings, with its name and description in your language)."""
    return [p.folder / "locales" / f"{code}.json" for p in discover().values()
            if (p.folder / "locales" / f"{code}.json").exists()]


def reset():
    """Forget what was found (tests, or after installing one)."""
    global _found
    _found = None
    _unfit.clear()


if __name__ == "__main__":  # bin/anyassistant plugins [requirements [--all]]
    args = sys.argv[1:]
    if args[:1] == ["requirements"]:
        print("\n".join(requirements(everything="--all" in args)))
        sys.exit(0)
    for p in describe():
        state = "on " if p["on"] else ("—  " if not wanted(p["id"]) else "!! ")
        notes = p["unfit"] + [f"command not found: {c}" for c in p["commands_missing"]]
        print(f"{state}{p['id']:20} {p['kind']:8} {'; '.join(notes)}")
