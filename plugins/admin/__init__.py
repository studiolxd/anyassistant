"""Admin: what the AnyAssistant app shows and changes, only from the Mac itself.

    GET  /admin/settings   the options by group, each with its value, kind, choices and help
                           (in the active language: locale «options», «groups»)
    POST /admin/settings   {"name": value, …} → saved; {"restart": true} if one needs it
    GET  /admin/plugins    every plugin: on, locked, why it can't work here, what it lacks
    POST /admin/plugins    {"id": true|false} → saved; whether packages must be installed
                           (bin/anyassistant setup packages) or the server restarted

From the Mac the user is the owner: unlike by voice, any plugin can be turned off here
(the app warns about the security and locked ones).
"""

import json

from aiohttp import web as http

import i18n
import kernel
import options
import settings
import web

LOCAL = {"127.0.0.1", "::1"}
ENGINES = {"brain", "stt", "wake", "llm", "tts", "vad"}  # chosen at start: a change restarts


def _local(handler):
    async def only_the_mac(request):
        if request.remote not in LOCAL:
            return http.json_response({}, status=403)
        return await handler(request)
    return only_the_mac


def _value(option):
    value = settings.load().get(option.name, settings.get(option.name, option.default))
    try:
        json.dumps(value)
    except TypeError:
        value = str(value)
    return value


def _choices(option):
    try:
        return [c for c in option.options()] if option.kind == "choice" else None
    except Exception:  # a list that couldn't be made now (a plugin off…)
        return None


@web.route("GET", "/admin/settings")
@_local
async def _settings(request):
    groups = [{"id": g, "title": i18n.L.text(f"groups.{g}", title)} for g, title in options.GROUPS.items()
              if g != "plugins"]
    found = [{"name": o.name, "group": o.group, "kind": o.kind, "live": o.live,
              "help": i18n.L.text(f"options.{o.name}", o.help), "default": _value_default(o),
              "value": _value(o), "choices": _choices(o)}
             for o in options.OPTIONS if o.group != "plugins"]
    return http.json_response({"groups": groups, "options": found})


def _value_default(option):
    try:
        json.dumps(option.default)
        return option.default
    except TypeError:
        return str(option.default)


@web.route("POST", "/admin/settings")
@_local
async def _save_settings(request):
    changes = await request.json()
    unknown = [k for k in changes if k not in options.BY_NAME]
    if unknown:
        return http.json_response({"error": f"unknown: {', '.join(unknown)}"}, status=400)
    problems = options.check(changes)
    if problems:
        return http.json_response({"error": "; ".join(problems)}, status=400)
    settings.save(**changes)
    settings.refresh()
    restart = any(not options.BY_NAME[k].live for k in changes)
    return http.json_response({"saved": list(changes), "restart": restart})


@web.route("GET", "/admin/plugins")
@_local
async def _plugins(request):
    found = []
    for p in kernel.describe():
        plugin = kernel.plugin(p["id"])
        found.append({**p, "name": i18n.L.text(f"plugins.{p['id']}.0", p["name"]),
                      "description": i18n.L.text(f"plugins.{p['id']}.1", p["description"]),
                      "locked": plugin.locked, "wanted": kernel.wanted(p["id"])})
    return http.json_response({"plugins": found})


@web.route("POST", "/admin/plugins")
@_local
async def _turn(request):
    changes = await request.json()
    chosen = dict(settings.load().get("plugins") or {})
    for plugin_id, on in changes.items():
        if not kernel.plugin(plugin_id):
            return http.json_response({"error": f"no plugin «{plugin_id}»"}, status=400)
        chosen[plugin_id] = bool(on)
    settings.save(plugins=chosen)
    settings.refresh()
    kernel._unfit.clear()
    packages = any(on and any(w.startswith("not installed") for w in kernel.unfit(pid))
                   for pid, on in changes.items())
    restart = packages or any(kernel.plugin(pid).kind in ENGINES for pid in changes)
    return http.json_response({"packages": packages, "restart": restart})
