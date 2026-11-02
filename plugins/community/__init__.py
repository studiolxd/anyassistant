"""The community: themes and plugins made by other people, from a public catalog, installed from
the app. The catalog is one JSON index (docs/comunidad.md: its format, how to publish) in a public
GitHub repository; «community_catalog» is its address.

    GET  /admin/community[?refresh=1]  the catalog: each package, what is installed and whether
                                       an update exists (and why one can't be installed here)
    POST /admin/community              {"install": {"kind", "id"}, "confirm": true}: installs or
                                       updates it; {"remove": {"kind", "id"}}: removes it
    GET  /admin/community/image?kind=theme&id=…   a theme's screenshot (fetched by the server,
                                       cached: the pages load nothing from outside)

Installing downloads every file of the package, checks its SHA-256 against the catalog, and only
then writes it, whole (to a staging folder next to its place, then moved) into your folder: a
theme to your themes folder («themes_dir»), a plugin to your plugins folder. A file that is
missing or doesn't match installs nothing. Never a system theme or plugin: a package with the
same id as one of the system's is refused, as is one with the id of a theme or plugin of your
own that didn't come from the catalog. What was installed (and its version) is kept in
community.json, to offer updates and removal.

A plugin is Python code that runs with your permissions: the server installs one only with
«confirm»: true (the app asks first, with a warning), and it starts off: you turn it on in
Plugins, after restarting. Themes are HTML and CSS the page cleans (no JavaScript): lower risk.

    bin/anyassistant community entry <folder> <base-url>   a package's entry for the index (cli.py)
"""

import asyncio
import hashlib
import json
import logging
import re
import shutil
import time
from pathlib import Path
from urllib.parse import urlsplit

import aiohttp
from aiohttp import web as http

import i18n
import kernel
import options
import paths
import settings
import web
from options import Option
from plugins.page import themes

log = logging.getLogger("community")

FORMAT = 1  # the index format this version understands
DEFAULT_CATALOG = "https://raw.githubusercontent.com/studiolxd/anyassistant-community/main/index.json"
FILE = paths.HOME / "community.json"  # what was installed from the catalog, and its version
KINDS = ("theme", "plugin")
ID = re.compile(r"[a-z0-9][a-z0-9_-]{0,30}")
PATH_PART = re.compile(r"[A-Za-z0-9_][A-Za-z0-9._-]*")
SHA256 = re.compile(r"[0-9a-f]{64}")
THEME_FILES = {".json", ".html", ".css"} | themes.ASSETS
MAX_FILE = 10 * 1024 * 1024
MAX_PACKAGE = 50 * 1024 * 1024
MAX_IMAGE = 3 * 1024 * 1024
MAX_INDEX = 2 * 1024 * 1024
CACHE_TIME = 600  # seconds the catalog is kept before asking again
TIMEOUT = aiohttp.ClientTimeout(total=120, connect=20)
STAGING = ".installing"  # inside the destination's folder: no theme.json or plugin.json right in it, so it's never listed

options.add(Option("community_catalog", DEFAULT_CATALOG,
                   "the community catalog: the address of its index (themes and plugins to install)", "server",
                   live=True))

_catalog: dict = {}  # the last index fetched: {"url", "time", "data"}
_lock = asyncio.Lock()  # one install or removal at a time


def _text(key: str, **values) -> str:
    return i18n.L.text(f"community.{key}", key).format(**values)


# --- Where things are ---

def version_here() -> int | None:
    """The installed version's number (VERSION: «1234-9e919ad»); None while developing: anything fits."""
    try:
        return int((paths.APP / "VERSION").read_text().split("-")[0].strip())
    except (OSError, ValueError):
        return None


def destination(kind: str, package_id: str) -> Path:
    """Where a package goes: your themes folder, or your plugins folder."""
    base = themes.folders()[1] if kind == "theme" else paths.USER_PLUGINS
    return base / package_id


def is_system(kind: str, package_id: str) -> bool:
    """Whether the system has a theme or plugin with that id (never replaced)."""
    if kind == "theme":
        return (themes.SYSTEM / package_id / "theme.json").exists()
    return (paths.PLUGINS / package_id / "plugin.json").exists()


def installed() -> dict:
    """{«kind:id»: {"kind", "id", "version", "name", "installed"}}: what came from the catalog."""
    try:
        found = json.loads(FILE.read_text()).get("installed", {})
        return found if isinstance(found, dict) else {}
    except (OSError, ValueError):
        return {}


def _save_installed(found: dict):
    FILE.parent.mkdir(parents=True, exist_ok=True)
    FILE.write_text(json.dumps({"installed": found}, ensure_ascii=False, indent=2) + "\n")


def _key(kind: str, package_id: str) -> str:
    return f"{kind}:{package_id}"


# --- The index ---

def _url_ok(url: str) -> bool:
    """Only HTTPS (plain HTTP only to this computer: tests and a local catalog)."""
    parts = urlsplit(str(url))
    if parts.scheme == "https":
        return bool(parts.netloc)
    return parts.scheme == "http" and parts.hostname in ("127.0.0.1", "localhost", "::1")


def _safe_path(path: str) -> bool:
    """A relative path inside the package: «locales/es.json», never «..», «/x» or odd characters."""
    parts = str(path).split("/")
    return bool(parts) and all(PATH_PART.fullmatch(p) and p not in (".", "..") for p in parts)


def check_entry(entry: dict) -> list[str]:
    """What is wrong in a package's entry of the index; empty if it's fine."""
    problems = []
    if not isinstance(entry, dict):
        return ["not an object"]
    kind, package_id = entry.get("kind"), str(entry.get("id", ""))
    if kind not in KINDS:
        problems.append(f"kind: {kind!r} is not one of {', '.join(KINDS)}")
    if not ID.fullmatch(package_id):
        problems.append("id: lowercase letters, numbers, - and _ (31 at most)")
    for key in ("name", "version"):
        if not isinstance(entry.get(key), str) or not entry[key].strip():
            problems.append(f"{key}: missing")
    if "min_version" in entry and not isinstance(entry["min_version"], int):
        problems.append("min_version: a whole number (the installed version's number)")
    if entry.get("screenshot") and not _url_ok(entry["screenshot"]):
        problems.append("screenshot: an https:// address")
    files = entry.get("files")
    if not isinstance(files, list) or not files:
        return problems + ["files: missing"]
    paths_seen = set()
    for file in files:
        if not isinstance(file, dict):
            problems.append("files: each one an object with path, url and sha256")
            continue
        path = str(file.get("path", ""))
        if not _safe_path(path):
            problems.append(f"files: «{path}» isn't a plain relative path")
        elif path in paths_seen:
            problems.append(f"files: «{path}» twice")
        paths_seen.add(path)
        if not _url_ok(file.get("url", "")):
            problems.append(f"files: «{path}» needs an https:// address")
        if not SHA256.fullmatch(str(file.get("sha256", "")).lower()):
            problems.append(f"files: «{path}» needs its sha256 (64 hex digits)")
        if kind == "theme" and Path(path).suffix.lower() not in THEME_FILES:
            problems.append(f"files: «{path}»: a theme can't have that kind of file")
    needed = {"theme.json", "theme.html", "theme.css"} if kind == "theme" else {"plugin.json", "__init__.py"}
    for missing in sorted(needed - paths_seen):
        problems.append(f"files: no {missing}")
    return problems


def parse_index(text: str) -> tuple[list[dict], list[str]]:
    """The index's packages (the valid ones), and what is wrong with the rest."""
    data = json.loads(text)
    if not isinstance(data, dict) or not isinstance(data.get("packages"), list):
        raise ValueError("the index needs «format» and a list «packages»")
    if int(data.get("format", 0)) > FORMAT:
        raise ValueError(f"the index is format {data.get('format')}: this version reads up to {FORMAT}")
    packages, problems = [], []
    for entry in data["packages"]:
        wrong = check_entry(entry)
        if wrong:
            problems.append(f"{entry.get('kind', '?')} «{entry.get('id', '?')}»: " + "; ".join(wrong)
                            if isinstance(entry, dict) else "; ".join(wrong))
        elif any(p["kind"] == entry["kind"] and p["id"] == entry["id"] for p in packages):
            problems.append(f"{entry['kind']} «{entry['id']}»: listed twice")
        else:
            packages.append(entry)
    return packages, problems


async def catalog(refresh: bool = False) -> dict:
    """The index, fetched (and kept a while): {"url", "packages", "problems"}."""
    url = settings.get("community_catalog") or DEFAULT_CATALOG
    if not refresh and _catalog.get("url") == url and time.time() - _catalog.get("time", 0) < CACHE_TIME:
        return _catalog["data"]
    if not _url_ok(url):
        raise ValueError(_text("catalog_address"))
    try:
        async with aiohttp.ClientSession(timeout=TIMEOUT, headers={"User-Agent": "AnyAssistant"}) as session:
            async with session.get(url) as answer:
                if answer.status != 200:
                    raise ValueError(_text("catalog_unreachable", url=url, why=f"HTTP {answer.status}"))
                text = (await answer.content.read(MAX_INDEX + 1)).decode("utf-8", "replace")
    except (aiohttp.ClientError, asyncio.TimeoutError, OSError) as e:
        raise ValueError(_text("catalog_unreachable", url=url, why=e.__class__.__name__)) from None
    if len(text) > MAX_INDEX:
        raise ValueError(_text("catalog_invalid", why="too big"))
    try:
        packages, problems = parse_index(text)
    except ValueError as e:
        raise ValueError(_text("catalog_invalid", why=str(e))) from None
    for problem in problems:
        log.warning("community catalog: %s", problem)
    _catalog.update(url=url, time=time.time(), data={"url": url, "packages": packages, "problems": problems})
    return _catalog["data"]


def _newer(catalog_version: str, installed_version: str) -> bool:
    try:
        from packaging.version import InvalidVersion, Version

        return Version(catalog_version) > Version(installed_version)
    except InvalidVersion:
        return catalog_version != installed_version


def describe(packages: list[dict]) -> list[dict]:
    """Each package for the app: what it is, what is installed, whether an update exists, and why
    it can't be installed here (if it can't)."""
    have, here = installed(), version_here()
    found = []
    for entry in packages:
        kind, package_id = entry["kind"], entry["id"]
        mine = have.get(_key(kind, package_id))
        why = ""
        if is_system(kind, package_id):
            why = _text(f"same_as_system_{kind}", id=package_id)
        elif mine is None and destination(kind, package_id).exists():
            why = _text(f"yours_{kind}", id=package_id)
        elif here is not None and int(entry.get("min_version", 0)) > here:
            why = _text("needs_version", version=entry["min_version"])
        found.append({"kind": kind, "id": package_id, "name": entry["name"], "author": entry.get("author", ""),
                      "version": entry["version"], "description": entry.get("description", ""),
                      "homepage": entry.get("homepage", ""), "screenshot": bool(entry.get("screenshot")),
                      "min_version": entry.get("min_version"), "installed": mine["version"] if mine else None,
                      "update": bool(mine) and _newer(entry["version"], mine["version"]),
                      "can": not why, "why": why})
    return found


# --- Installing, updating, removing ---

def _entry(packages: list[dict], kind: str, package_id: str) -> dict:
    for entry in packages:
        if entry["kind"] == kind and entry["id"] == package_id:
            return entry
    raise ValueError(_text("not_in_catalog", id=package_id))


async def _download(session: aiohttp.ClientSession, file: dict, into: Path) -> int:
    """One file of the package to the staging folder, checked against its SHA-256; its size."""
    target = into / file["path"]
    target.parent.mkdir(parents=True, exist_ok=True)
    digest, size = hashlib.sha256(), 0
    try:
        async with session.get(file["url"]) as answer:
            if answer.status != 200:
                raise ValueError(_text("missing", path=file["path"], why=f"HTTP {answer.status}"))
            with target.open("wb") as out:
                async for chunk in answer.content.iter_chunked(64 * 1024):
                    size += len(chunk)
                    if size > MAX_FILE:
                        raise ValueError(_text("too_big", path=file["path"]))
                    digest.update(chunk)
                    out.write(chunk)
    except (aiohttp.ClientError, asyncio.TimeoutError, OSError) as e:
        raise ValueError(_text("missing", path=file["path"], why=e.__class__.__name__)) from None
    if digest.hexdigest() != file["sha256"].lower():
        raise ValueError(_text("mismatch", path=file["path"]))
    return size


def _check_downloaded(kind: str, folder: Path):
    """What was downloaded, before it is put in place: a theme the page accepts, a plugin whose
    manifest is plain (never a security or locked one: those are the system's)."""
    if kind == "theme":
        problems = themes.check(folder)
        if problems:
            raise ValueError(_text("bad_theme", why="; ".join(problems)))
        return
    try:
        manifest = json.loads((folder / "plugin.json").read_text())
    except ValueError as e:
        raise ValueError(_text("bad_plugin", why=f"plugin.json isn't valid JSON: {e}")) from None
    if not isinstance(manifest, dict) or not manifest.get("name"):
        raise ValueError(_text("bad_plugin", why="plugin.json: no «name»"))
    if manifest.get("security") or manifest.get("locked"):
        raise ValueError(_text("bad_plugin", why="it says it is a security (or locked) plugin: only the system's are"))
    if manifest.get("kind", "feature") not in kernel.KINDS:
        raise ValueError(_text("bad_plugin", why=f"plugin.json: kind «{manifest.get('kind')}» isn't one"))


def _put_in_place(staged: Path, target: Path):
    """The staged folder takes the target's place, whole: the old one goes aside, then away."""
    old = staged.parent / f"{target.name}.old"
    shutil.rmtree(old, ignore_errors=True)
    if target.exists():
        target.rename(old)
    try:
        staged.rename(target)
    except OSError:
        if old.exists():
            old.rename(target)
        raise
    shutil.rmtree(old, ignore_errors=True)


async def install(kind: str, package_id: str, confirm: bool = False) -> dict:
    """Installs (or updates) a package from the catalog; what was done. ValueError says why not."""
    if kind not in KINDS:
        raise ValueError(_text("not_in_catalog", id=package_id))
    if kind == "plugin" and not confirm:
        raise ValueError(_text("confirm_plugin"))
    found = await catalog()
    entry = _entry(found["packages"], kind, package_id)
    shown = describe([entry])[0]
    if not shown["can"]:
        raise ValueError(shown["why"])
    target = destination(kind, package_id)
    async with _lock:
        staging = target.parent / STAGING
        staged = staging / package_id
        shutil.rmtree(staged, ignore_errors=True)
        staged.mkdir(parents=True)
        try:
            total = 0
            async with aiohttp.ClientSession(timeout=TIMEOUT, headers={"User-Agent": "AnyAssistant"}) as session:
                for file in entry["files"]:
                    total += await _download(session, file, staged)
                    if total > MAX_PACKAGE:
                        raise ValueError(_text("too_big", path=package_id))
            _check_downloaded(kind, staged)
            _put_in_place(staged, target)
        except BaseException:
            shutil.rmtree(staged, ignore_errors=True)
            raise
        finally:
            try:
                staging.rmdir()  # only if nothing is left in it
            except OSError:
                pass
        updated = shown["installed"] is not None
        have = installed()
        have[_key(kind, package_id)] = {"kind": kind, "id": package_id, "name": entry["name"],
                                        "version": entry["version"], "installed": time.time(),
                                        "files": [f["path"] for f in entry["files"]]}
        _save_installed(have)
    if kind == "plugin":
        if not updated:  # off until you turn it on (an update keeps your choice)
            chosen = dict(settings.load().get("plugins") or {})
            chosen[package_id] = False
            settings.save(plugins=chosen)
            settings.refresh()
        kernel.reset()
    log.info("community: %s «%s» %s (%s)", kind, package_id, "updated" if updated else "installed", entry["version"])
    return {"kind": kind, "id": package_id, "version": entry["version"], "updated": updated,
            "restart": kind == "plugin"}


def remove(kind: str, package_id: str) -> dict:
    """Removes a package that came from the catalog (never anything else)."""
    have = installed()
    record = have.get(_key(kind, package_id))
    if not record:
        raise ValueError(_text("not_installed", id=package_id))
    if kind == "theme" and settings.get("theme") == package_id:
        raise ValueError(_text("theme_in_use"))
    target = destination(kind, package_id)
    if target.exists():
        shutil.rmtree(target)
    del have[_key(kind, package_id)]
    _save_installed(have)
    if kind == "plugin":
        chosen = dict(settings.load().get("plugins") or {})
        if package_id in chosen:
            del chosen[package_id]
            settings.save(plugins=chosen)
            settings.refresh()
        kernel.reset()
    log.info("community: %s «%s» removed", kind, package_id)
    return {"kind": kind, "id": package_id, "removed": True, "restart": kind == "plugin"}


# --- For the app and the admin page ---

@web.route("GET", "/admin/community")
@web.only_the_owner
async def _list(request):
    try:
        found = await catalog(refresh=request.query.get("refresh") == "1")
    except ValueError as e:
        return http.json_response({"catalog": settings.get("community_catalog") or DEFAULT_CATALOG,
                                   "version": version_here(), "packages": [], "error": str(e)})
    return http.json_response({"catalog": found["url"], "version": version_here(),
                               "packages": describe(found["packages"]), "problems": found["problems"]})


@web.route("POST", "/admin/community")
@web.only_the_owner
async def _change(request):
    data = await request.json()
    try:
        if isinstance(data.get("install"), dict):
            asked = data["install"]
            if asked.get("kind") == "plugin" and not data.get("confirm"):
                return http.json_response({"error": _text("confirm_plugin"), "confirm": "plugin"}, status=400)
            return http.json_response(await install(str(asked.get("kind")), str(asked.get("id")),
                                                    confirm=bool(data.get("confirm"))))
        if isinstance(data.get("remove"), dict):
            asked = data["remove"]
            return http.json_response(remove(str(asked.get("kind")), str(asked.get("id"))))
    except ValueError as e:
        return http.json_response({"error": str(e)}, status=400)
    return http.json_response({"error": "install or remove"}, status=400)


@web.route("GET", "/admin/community/image")
@web.only_the_owner
async def _image(request):
    """A theme's screenshot, as the catalog lists it, fetched by the server and kept in the cache."""
    kind, package_id = request.query.get("kind", "theme"), request.query.get("id", "")
    try:
        entry = _entry((await catalog())["packages"], kind, package_id)
    except ValueError:
        raise http.HTTPNotFound()
    url = entry.get("screenshot")
    if not url:
        raise http.HTTPNotFound()
    folder = paths.CACHE / "community"
    cached = folder / f"{kind}-{package_id}-{hashlib.sha256(url.encode()).hexdigest()[:12]}"
    if not cached.exists():
        try:
            async with aiohttp.ClientSession(timeout=TIMEOUT, headers={"User-Agent": "AnyAssistant"}) as session:
                async with session.get(url) as answer:
                    if answer.status != 200 or not answer.content_type.startswith("image/"):
                        raise http.HTTPNotFound()
                    body = await answer.content.read(MAX_IMAGE + 1)
        except (aiohttp.ClientError, asyncio.TimeoutError, OSError):
            raise http.HTTPNotFound()
        if len(body) > MAX_IMAGE:
            raise http.HTTPNotFound()
        folder.mkdir(parents=True, exist_ok=True)
        cached.write_bytes(body)
        (cached.with_suffix(".type")).write_text(answer.content_type)
    try:
        content_type = cached.with_suffix(".type").read_text().strip() or "image/png"
    except OSError:
        content_type = "image/png"
    return http.Response(body=cached.read_bytes(), content_type=content_type,
                         headers={"Cache-Control": "max-age=3600"})
