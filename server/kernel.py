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

«kind» is what it is: stt, wake, llm, tts, vad (engines: the settings choose one),
skill, or feature. Every plugin found is loaded (importing one must be cheap:
heavy libraries only inside its classes); whether it is ON is checked when it is
used, from settings «plugins» ({"memory": false}) or its manifest's «default»
(true unless it says otherwise). So most can be turned on and off without
restarting. Plugins import each other as plugins.<id with underscores>.
"""

import importlib.util
import json
import logging
import sys
import types
from dataclasses import dataclass, field
from pathlib import Path

import paths

log = logging.getLogger("kernel")
KINDS = ("stt", "wake", "llm", "tts", "vad", "skill", "feature")


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


def enabled(plugin_id: str | None) -> bool:
    """Whether a plugin is on (and so are the ones it needs). None: the core's own."""
    if plugin_id is None:
        return True
    found = plugin(plugin_id)
    if not found:
        return False
    on = choices().get(plugin_id, found.manifest.get("default", True))
    return bool(on) and all(enabled(r) for r in found.requires)


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
             "yours": p.yours, "requires": p.requires} for p in discover().values()]


def locale_files(code: str) -> list[Path]:
    """The plugins' texts for a language (only those that are on)."""
    return [p.folder / "locales" / f"{code}.json" for p in discover().values()
            if enabled(p.id) and (p.folder / "locales" / f"{code}.json").exists()]


def reset():
    """Forget what was found (tests, or after installing one)."""
    global _found
    _found = None
