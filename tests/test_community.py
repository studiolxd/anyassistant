"""The community catalog (plugin «community»): themes and plugins from a public index, installed
only when every file matches its SHA-256, never over the system's; updates and removal; a plugin
only with the user's confirmation, and off at first."""

import asyncio
import hashlib
import json

import pytest
from aiohttp import web as http
from aiohttp.test_utils import TestServer, make_mocked_request

import kernel
import paths
import settings

community = kernel.load("community")
from conftest import ROOT

THEME = {"theme.json": json.dumps({"name": "Aurora", "author": "Ana", "version": "1.0.0", "description": "Northern lights"}),
         "theme.html": '<div data-block="face"></div><p data-block="status"></p>',
         "theme.css": "body { background: #023; }",
         "locales/es.json": json.dumps({"ui": {"thinking": "Mmm…"}})}
PLUGIN = {"plugin.json": json.dumps({"name": "Greeter", "description": "Says hi", "kind": "skill", "author": "Bo", "version": "2.1"}),
          "__init__.py": "# says hi\n",
          "locales/es.json": json.dumps({"plugins": {"greeter": ["Saludador", "Saluda"]}})}


@pytest.fixture
def mine(tmp_path, monkeypatch):
    """Your themes and plugins folders, the record of what was installed, and no catalog kept."""
    monkeypatch.setattr(settings, "active", {"themes_dir": str(tmp_path / "themes"), "community_catalog": None})
    monkeypatch.setattr(settings, "PATH", tmp_path / "settings.json")
    monkeypatch.setattr(paths, "USER_PLUGINS", tmp_path / "plugins")
    monkeypatch.setattr(paths, "CACHE", tmp_path / "cache")
    monkeypatch.setattr(community, "FILE", tmp_path / "community.json")
    monkeypatch.setattr(community, "_catalog", {})
    # The plugins found again, with your folder; the ones found before (their modules loaded) come
    # back afterwards: nothing here loads a plugin's module anew.
    monkeypatch.setattr(kernel, "_found", None)
    monkeypatch.setattr(kernel, "_unfit", {})
    return tmp_path


class Catalog:
    """A fake catalog on this computer: an index and the packages' files, served by aiohttp.
    Files can be changed or dropped after the index is made (a mismatch, a missing one)."""

    def __init__(self, base: str = ""):
        self.files: dict[str, bytes] = {}
        self.packages: list[dict] = []
        self.index: dict | None = None
        self.url = ""

    def package(self, kind: str, package_id: str, files: dict, version: str = "1.0.0", **more) -> dict:
        entry = {"kind": kind, "id": package_id, "name": package_id.title(), "author": "Someone", "version": version,
                 "description": f"A {kind}", "files": [], **more}
        for path, content in files.items():
            data = content.encode() if isinstance(content, str) else content
            self.files[f"{kind}s/{package_id}/{path}"] = data
            entry["files"].append({"path": path, "url": f"{{base}}/{kind}s/{package_id}/{path}",
                                   "sha256": hashlib.sha256(data).hexdigest()})
        self.packages = [p for p in self.packages if (p["kind"], p["id"]) != (kind, package_id)] + [entry]
        return entry

    def app(self) -> http.Application:
        async def index(request):
            data = self.index or {"format": 1, "packages": self.packages}
            return http.Response(text=json.dumps(data).replace("{base}", self.url), content_type="application/json")

        async def file(request):
            data = self.files.get(request.match_info["path"])
            if data is None:
                raise http.HTTPNotFound()
            return http.Response(body=data, content_type="image/png" if request.path.endswith(".png") else "application/octet-stream")

        app = http.Application()
        app.router.add_get("/index.json", index)
        app.router.add_get("/{path:.+}", file)
        return app


def serve(test):
    """Runs an async test with a catalog served on 127.0.0.1 (settings «community_catalog» points at it)."""
    async def go():
        catalog = Catalog()
        server = TestServer(catalog.app())
        await server.start_server()
        try:
            catalog.url = f"http://127.0.0.1:{server.port}"
            settings.active["community_catalog"] = catalog.url + "/index.json"
            await test(catalog)
        finally:
            await server.close()
    asyncio.run(go())


def request(method="GET", path="/admin/community", body=None, remote="127.0.0.1"):
    made = make_mocked_request(method, path, headers={"User-Agent": "test"},
                               transport=type("T", (), {"get_extra_info": lambda self, k, d=None:
                                                        (remote, 1) if k == "peername" else d})())
    if body is not None:
        async def read_json():
            return body
        made.json = read_json
    return made


async def listed(refresh=True) -> dict:
    return json.loads((await community._list(request(path=f"/admin/community?refresh={int(refresh)}"))).body)


async def change(body: dict):
    answer = await community._change(request("POST", body=body))
    return answer.status, json.loads(answer.body)


# --- Listing ---

def test_the_catalog_lists_what_is_installed_and_what_can_be(mine):
    async def test(catalog):
        catalog.package("theme", "aurora", THEME)
        catalog.package("plugin", "greeter", PLUGIN, version="2.1")
        catalog.package("theme", "eyes", THEME)  # a system theme's id
        catalog.package("plugin", "memory", PLUGIN)  # a system plugin's id
        catalog.package("theme", "future", THEME, min_version=10 ** 9)
        found = await listed()
        by_id = {(p["kind"], p["id"]): p for p in found["packages"]}
        assert by_id[("theme", "aurora")]["installed"] is None and by_id[("theme", "aurora")]["can"]
        assert not by_id[("theme", "eyes")]["can"] and "system" in by_id[("theme", "eyes")]["why"]
        assert not by_id[("plugin", "memory")]["can"] and "system" in by_id[("plugin", "memory")]["why"]
        if community.version_here() is None:  # while developing anything fits
            assert by_id[("theme", "future")]["can"]
        else:
            assert not by_id[("theme", "future")]["can"]
        assert found["error" if "error" in found else "problems"] in ("", [])
    serve(test)


def test_a_bad_index_or_an_unreachable_catalog_is_said(mine):
    async def test(catalog):
        catalog.index = {"format": 99, "packages": []}
        assert "format 99" in (await listed())["error"]
        catalog.index = {"format": 1, "packages": [{"kind": "theme", "id": "no-files", "name": "x", "version": "1"},
                                                   {"kind": "theme", "id": "../evil", "name": "x", "version": "1",
                                                    "files": [{"path": "../x", "url": "https://h/x", "sha256": "0" * 64}]},
                                                   {"kind": "plugin", "id": "fine", "name": "x", "version": "1",
                                                    "files": [{"path": "plugin.json", "url": "https://h/p", "sha256": "0" * 64},
                                                              {"path": "__init__.py", "url": "https://h/i", "sha256": "1" * 64}]}]}
        found = await listed()
        assert [p["id"] for p in found["packages"]] == ["fine"]  # the broken ones are left out, and said
        assert len(found["problems"]) == 2
        settings.active["community_catalog"] = "http://example.com/index.json"  # not https: refused
        assert "https" in (await listed())["error"]
        settings.active["community_catalog"] = "https://127.0.0.1:1/index.json"  # nothing listens
        assert "couldn't be read" in (await listed())["error"]
    serve(test)


def test_only_the_owner(mine):
    answer = asyncio.run(community._list(request(remote="192.168.1.9")))
    assert answer.status == 403


# --- Installing ---

def test_a_theme_installs_whole_and_is_recorded(mine):
    async def test(catalog):
        catalog.package("theme", "aurora", THEME)
        status, answer = await change({"install": {"kind": "theme", "id": "aurora"}})
        assert status == 200 and answer == {"kind": "theme", "id": "aurora", "version": "1.0.0", "updated": False, "restart": False}
        folder = mine / "themes" / "aurora"
        assert (folder / "theme.css").read_text() == THEME["theme.css"]
        assert (folder / "locales" / "es.json").exists()
        assert not (mine / "themes" / community.STAGING).exists()
        assert community.installed()["theme:aurora"]["version"] == "1.0.0"
        assert "aurora" in community.themes.available() and not community.themes.is_system("aurora")
        shown = {p["id"]: p for p in (await listed())["packages"]}["aurora"]
        assert shown["installed"] == "1.0.0" and not shown["update"]
    serve(test)


def test_a_hash_mismatch_installs_nothing(mine):
    async def test(catalog):
        catalog.package("theme", "aurora", THEME)
        catalog.files["themes/aurora/theme.css"] = b"body { background: url(https://evil) }"  # changed after review
        status, answer = await change({"install": {"kind": "theme", "id": "aurora"}})
        assert status == 400 and "SHA-256" in answer["error"]
        assert not (mine / "themes" / "aurora").exists()
        assert not (mine / "themes" / community.STAGING).exists()
        assert community.installed() == {}
    serve(test)


def test_a_missing_file_installs_nothing(mine):
    async def test(catalog):
        catalog.package("theme", "aurora", THEME)
        del catalog.files["themes/aurora/theme.css"]
        status, answer = await change({"install": {"kind": "theme", "id": "aurora"}})
        assert status == 400 and "theme.css" in answer["error"] and "404" in answer["error"]
        assert not (mine / "themes").exists() or not list((mine / "themes").iterdir())
        assert community.installed() == {}
    serve(test)


def test_never_a_system_theme_or_plugin(mine):
    async def test(catalog):
        catalog.package("theme", "eyes", THEME)
        catalog.package("plugin", "memory", PLUGIN)
        status, answer = await change({"install": {"kind": "theme", "id": "eyes"}})
        assert status == 400 and "system theme" in answer["error"]
        status, answer = await change({"install": {"kind": "plugin", "id": "memory"}, "confirm": True})
        assert status == 400 and "system plugin" in answer["error"]
        assert not (mine / "themes" / "eyes").exists() and not (mine / "plugins" / "memory").exists()
        assert (ROOT / "plugins" / "memory" / "__init__.py").exists()  # untouched
    serve(test)


def test_never_over_one_of_your_own(mine):
    async def test(catalog):
        catalog.package("theme", "aurora", THEME)
        own = mine / "themes" / "aurora"
        own.mkdir(parents=True)
        (own / "theme.json").write_text('{"name": "My aurora"}')
        shown = {p["id"]: p for p in (await listed())["packages"]}["aurora"]
        assert not shown["can"] and "your own" in shown["why"]
        status, answer = await change({"install": {"kind": "theme", "id": "aurora"}})
        assert status == 400 and (own / "theme.json").read_text() == '{"name": "My aurora"}'
    serve(test)


def test_a_theme_with_problems_installs_nothing(mine):
    async def test(catalog):
        catalog.package("theme", "broken", {**THEME, "theme.html": "<p>nothing to show</p>"})
        status, answer = await change({"install": {"kind": "theme", "id": "broken"}})
        assert status == 400 and "face" in answer["error"]
        assert not (mine / "themes" / "broken").exists()
    serve(test)


def test_a_plugin_needs_your_confirmation_and_starts_off(mine):
    async def test(catalog):
        catalog.package("plugin", "greeter", PLUGIN, version="2.1")
        status, answer = await change({"install": {"kind": "plugin", "id": "greeter"}})
        assert status == 400 and answer["confirm"] == "plugin"
        assert not (mine / "plugins" / "greeter").exists()
        status, answer = await change({"install": {"kind": "plugin", "id": "greeter"}, "confirm": True})
        assert status == 200 and answer["restart"]
        assert (mine / "plugins" / "greeter" / "__init__.py").exists()
        assert settings.load()["plugins"] == {"greeter": False}
        found = kernel.plugin("greeter")
        assert found and found.yours and not kernel.enabled("greeter")
        assert community.installed()["plugin:greeter"]["version"] == "2.1"
    serve(test)


def test_a_plugin_that_calls_itself_security_is_refused(mine):
    async def test(catalog):
        manifest = json.dumps({"name": "Sneaky", "kind": "feature", "security": True})
        catalog.package("plugin", "sneaky", {**PLUGIN, "plugin.json": manifest})
        status, answer = await change({"install": {"kind": "plugin", "id": "sneaky"}, "confirm": True})
        assert status == 400 and "security" in answer["error"]
        assert not (mine / "plugins" / "sneaky").exists()
    serve(test)


# --- Updating and removing ---

def test_an_update_replaces_it_whole_and_keeps_your_choice(mine):
    async def test(catalog):
        catalog.package("plugin", "greeter", PLUGIN, version="2.1")
        await change({"install": {"kind": "plugin", "id": "greeter"}, "confirm": True})
        settings.save(plugins={"greeter": True})  # you turned it on
        newer = {"plugin.json": json.dumps({"name": "Greeter", "kind": "skill", "version": "3.0"}), "__init__.py": "# v3\n"}
        catalog.package("plugin", "greeter", newer, version="3.0")  # no locales any more
        shown = {p["id"]: p for p in (await listed())["packages"]}["greeter"]
        assert shown["installed"] == "2.1" and shown["update"]
        status, answer = await change({"install": {"kind": "plugin", "id": "greeter"}, "confirm": True})
        assert status == 200 and answer["updated"] and answer["version"] == "3.0"
        folder = mine / "plugins" / "greeter"
        assert (folder / "__init__.py").read_text() == "# v3\n"
        assert not (folder / "locales").exists()  # the old version's files are gone
        assert settings.load()["plugins"] == {"greeter": True}
        assert community.installed()["plugin:greeter"]["version"] == "3.0"
        shown = {p["id"]: p for p in (await listed())["packages"]}["greeter"]
        assert shown["installed"] == "3.0" and not shown["update"]
    serve(test)


def test_a_failed_update_leaves_the_old_one(mine):
    async def test(catalog):
        catalog.package("theme", "aurora", THEME)
        await change({"install": {"kind": "theme", "id": "aurora"}})
        catalog.package("theme", "aurora", {**THEME, "theme.css": "body { background: #000; }"}, version="1.1.0")
        catalog.files["themes/aurora/theme.css"] = b"tampered"
        status, answer = await change({"install": {"kind": "theme", "id": "aurora"}})
        assert status == 400
        assert (mine / "themes" / "aurora" / "theme.css").read_text() == THEME["theme.css"]
        assert community.installed()["theme:aurora"]["version"] == "1.0.0"
    serve(test)


def test_removing(mine):
    async def test(catalog):
        catalog.package("theme", "aurora", THEME)
        catalog.package("plugin", "greeter", PLUGIN)
        await change({"install": {"kind": "theme", "id": "aurora"}})
        await change({"install": {"kind": "plugin", "id": "greeter"}, "confirm": True})
        settings.active["theme"] = "aurora"
        status, answer = await change({"remove": {"kind": "theme", "id": "aurora"}})
        assert status == 400 and "in use" in answer["error"]  # choose another first
        settings.active["theme"] = "eyes"
        status, answer = await change({"remove": {"kind": "theme", "id": "aurora"}})
        assert status == 200 and not (mine / "themes" / "aurora").exists()
        status, answer = await change({"remove": {"kind": "plugin", "id": "greeter"}})
        assert status == 200 and answer["restart"] and not (mine / "plugins" / "greeter").exists()
        assert kernel.plugin("greeter") is None
        assert community.installed() == {} and settings.load().get("plugins") == {}
        # One of your own, not from the catalog: never
        own = mine / "themes" / "mine"
        own.mkdir(parents=True)
        (own / "theme.json").write_text("{}")
        status, answer = await change({"remove": {"kind": "theme", "id": "mine"}})
        assert status == 400 and own.exists()
    serve(test)


# --- Updates announced ---

async def waiting(remote="127.0.0.1"):
    answer = await community._updates(request(path="/admin/community/updates", remote=remote))
    return answer.status, json.loads(answer.body)


def test_updates_are_announced_once_per_new_version(mine):
    async def test(catalog):
        catalog.package("theme", "aurora", THEME)
        catalog.package("plugin", "greeter", PLUGIN, version="2.1")
        catalog.package("theme", "other", THEME)  # in the catalog, not installed: never announced
        await change({"install": {"kind": "theme", "id": "aurora"}})
        await change({"install": {"kind": "plugin", "id": "greeter"}, "confirm": True})
        assert await community.look_for_updates() == []
        status, answer = await waiting()
        assert status == 200 and answer == {"updates": [], "notice": None}

        catalog.package("theme", "aurora", THEME, version="1.1.0")
        new = await community.look_for_updates()
        assert new == [{"kind": "theme", "id": "aurora", "name": "Aurora", "from": "1.0.0", "to": "1.1.0"}]
        _, answer = await waiting()
        first = answer["notice"]["id"]
        assert answer["updates"] == new and first >= 1 and answer["notice"]["updates"] == new
        # Looked for again (another day, a restart): the same version isn't announced again
        assert await community.look_for_updates() == []
        _, answer = await waiting()
        assert answer["notice"]["id"] == first and answer["updates"] == new

        # Another version of the plugin: a new notice, with only it; the theme still waits
        catalog.package("plugin", "greeter", PLUGIN, version="2.2")
        new = await community.look_for_updates()
        assert [(u["id"], u["from"], u["to"]) for u in new] == [("greeter", "2.1", "2.2")]
        _, answer = await waiting()
        assert answer["notice"]["id"] > first and [u["id"] for u in answer["notice"]["updates"]] == ["greeter"]
        assert sorted(u["id"] for u in answer["updates"]) == ["aurora", "greeter"]

        # Installed: no longer waiting, nor in the notice; nothing was installed by itself
        assert community.installed()["plugin:greeter"]["version"] == "2.1"
        await change({"install": {"kind": "plugin", "id": "greeter"}, "confirm": True})
        _, answer = await waiting()
        assert [u["id"] for u in answer["updates"]] == ["aurora"] and answer["notice"]["updates"] == []
        assert "installed" in json.loads((mine / "community.json").read_text())
    serve(test)


def test_an_update_that_needs_a_newer_version_isnt_announced(mine):
    async def test(catalog):
        catalog.package("theme", "aurora", THEME)
        await change({"install": {"kind": "theme", "id": "aurora"}})
        catalog.package("theme", "aurora", THEME, version="2.0", min_version=10 ** 9)
        new = await community.look_for_updates()
        assert new == ([{"kind": "theme", "id": "aurora", "name": "Aurora", "from": "1.0.0", "to": "2.0"}]
                       if community.version_here() is None else [])
    serve(test)


def test_updates_only_for_the_owner(mine):
    status, _ = asyncio.run(waiting(remote="192.168.1.9"))
    assert status == 403


def test_updates_are_looked_for_only_with_something_installed(mine, monkeypatch):
    looked = []

    async def look():
        looked.append(1)
        return []

    monkeypatch.setattr(community, "FIRST_CHECK", 0)
    monkeypatch.setattr(community, "look_for_updates", look)
    monkeypatch.setattr(kernel, "enabled", lambda plugin_id: True)
    slept = asyncio.sleep

    async def go():
        app = {}
        monkeypatch.setattr(asyncio, "sleep", lambda seconds: slept(0))
        await community._watch(app)
        await slept(0.01)
        assert looked == []  # nothing installed: the catalog isn't read
        community._save_installed({"theme:aurora": {"kind": "theme", "id": "aurora", "version": "1.0.0"}})
        await slept(0.01)
        assert looked == [1]  # once, then not again for a day
        app["community-updates"].cancel()
    asyncio.run(go())


def test_a_themes_screenshot_comes_through_the_server(mine):
    async def test(catalog):
        catalog.package("theme", "aurora", THEME, screenshot="{base}/themes/aurora/preview.png")
        catalog.files["themes/aurora/preview.png"] = b"\x89PNG fake"
        answer = await community._image(request(path="/admin/community/image?kind=theme&id=aurora"))
        assert answer.status == 200 and answer.body == b"\x89PNG fake" and answer.content_type == "image/png"
        del catalog.files["themes/aurora/preview.png"]
        answer = await community._image(request(path="/admin/community/image?kind=theme&id=aurora"))
        assert answer.body == b"\x89PNG fake"  # kept in the cache
        with pytest.raises(http.HTTPNotFound):
            await community._image(request(path="/admin/community/image?kind=theme&id=nope"))
    serve(test)


# --- Publishing: an entry for the index ---

def test_an_entry_for_the_index(tmp_path):
    from conftest import load_script  # noqa: F401  (the cli is plain Python: imported directly)
    import importlib.util

    spec = importlib.util.spec_from_file_location("community_cli", ROOT / "plugins" / "community" / "cli.py")
    cli = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(cli)
    folder = tmp_path / "aurora"
    (folder / "locales").mkdir(parents=True)
    for path, content in THEME.items():
        (folder / path).write_text(content)
    (folder / "preview.png").write_bytes(b"png")
    (folder / ".DS_Store").write_bytes(b"junk")
    made = cli.entry(folder, "https://raw.githubusercontent.com/x/y/main/themes/aurora/")
    assert made["kind"] == "theme" and made["id"] == "aurora" and made["name"] == "Aurora" and made["author"] == "Ana"
    assert made["screenshot"].endswith("/themes/aurora/preview.png")
    assert {f["path"] for f in made["files"]} == set(THEME) | {"preview.png"}
    assert community.check_entry(made) == []
    css = next(f for f in made["files"] if f["path"] == "theme.css")
    assert css["sha256"] == hashlib.sha256(THEME["theme.css"].encode()).hexdigest()
    assert css["url"] == "https://raw.githubusercontent.com/x/y/main/themes/aurora/theme.css"


def test_the_example_index_is_valid():
    text = (ROOT / "docs" / "comunidad" / "index.example.json").read_text()
    packages, problems = community.parse_index(text)
    assert problems == [] and {p["kind"] for p in packages} == {"theme", "plugin"}
