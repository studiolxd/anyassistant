"""Jarvis's plugins, as tools: which there are, and turning them on and off (with the
user's «yes» to turn one off). Never a security plugin, nor this one, nor an engine
in use (choose another first): nobody can lift a safeguard by talking.
"""

import kernel
import settings
from tools import ToolError, tool

ENGINES = {"stt": "stt", "wake": "wake", "llm": "llm", "tts": "tts", "vad": "vad"}  # kind: the setting choosing one


def _in_use(found) -> bool:
    """Whether it is the engine the settings use now (its class registered under that name)."""
    if found.kind not in ENGINES:
        return False
    module = __import__(found.kind)
    chosen = settings.get(ENGINES[found.kind])
    plugin_class = module.get(chosen) if chosen else None
    return bool(plugin_class and plugin_class.plugin == found.id)


@tool("Jarvis's plugins: what each does, whether it is on, and which are yours.")
def list_plugins() -> str:
    lines = []
    for p in kernel.describe():
        marks = [("on" if p["on"] else "off")] + (["security"] if p["security"] else []) + (["yours"] if p["yours"] else [])
        lines.append(f"{p['id']} ({p['kind']}, {', '.join(marks)}): {p['name']}. {p['description']}")
    return "\n".join(lines)


def _set(plugin_id: str, on: bool) -> str:
    found = kernel.plugin(plugin_id)
    if not found:
        raise ToolError(f"no plugin «{plugin_id}» (list_plugins)")
    if not on and (found.security or found.id == "plugin-manager"):
        raise ToolError(f"«{plugin_id}» is a security plugin: it can only be turned off in settings.json, by hand")
    if not on and _in_use(found):
        raise ToolError(f"«{plugin_id}» is the {found.kind} in use: choose another one first")
    chosen = dict(settings.load().get("plugins") or {})
    chosen[plugin_id] = on
    settings.save(plugins=chosen)
    settings.refresh()
    needing = [p.id for p in kernel.discover().values() if plugin_id in p.requires]
    note = f" These need it and are off with it: {', '.join(needing)}." if needing and not on else ""
    return ("On." if on else "Off.") + note


@tool("Turn one of Jarvis's plugins on (its id from list_plugins).")
def enable_plugin(plugin_id: str) -> str:
    return _set(plugin_id, True)


@tool("Turn one of Jarvis's plugins off (its id from list_plugins); not security plugins.", needs_yes=True)
def disable_plugin(plugin_id: str) -> str:
    return _set(plugin_id, False)
