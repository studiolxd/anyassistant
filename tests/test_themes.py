"""Themes: anyone's HTML and CSS, cleaned and contained; the system's ones; sounds and texts."""

import json

import pytest

import settings
import kernel

themes = kernel.load("page").themes
from conftest import ROOT


@pytest.fixture
def mine(tmp_path, monkeypatch):
    """A themes_dir of your own, with a theme to play with."""
    monkeypatch.setattr(settings, "active", {"themes_dir": str(tmp_path)})
    theme = tmp_path / "mine"
    theme.mkdir()
    (theme / "theme.json").write_text(json.dumps({"name": "Mine", "options": {"accent": "#123456"}}))
    (theme / "theme.html").write_text('<div data-block="face"></div><p data-block="status"></p>')
    (theme / "theme.css").write_text("body { color: red; }")
    return theme


def test_system_themes_are_fine():
    assert {"eyes", "orb", "minimal", "bedside"} <= set(themes.available())
    for name in ("eyes", "orb", "minimal", "bedside"):
        assert themes.check(ROOT / "plugins" / "page" / "themes" / name) == [], name


@pytest.mark.parametrize("html, kept, gone", [
    ('<p onclick="steal()">hi</p>', "<p>hi</p>", "onclick"),
    ('<script>fetch("//evil")</script><p>x</p>', "<p>x</p>", "script"),
    ('<img src="https://tracker.example/x.png">', "<img>", "tracker"),
    ('<img src="//tracker.example/x.png">', "<img>", "tracker"),
    ('<a href="javascript:alert(1)">x</a>', "<a>x</a>", "javascript"),
    ('<img src="../../settings.json">', "<img>", "settings"),
    ('<iframe src="x.html"></iframe><p>y</p>', "<p>y</p>", "iframe"),
    ('<div style="background:url(https://x)">z</div>', "<div>z</div>", "url("),
    ('<img src="images/me.png" alt="me">', '<img src="/theme/s/images/me.png" alt="me">', None),
])
def test_cleaning(html, kept, gone):
    cleaned, _ = themes.clean(html, base="/theme/s/")
    assert cleaned == kept
    if gone:
        assert gone not in cleaned


def test_your_themes_and_their_options(mine, monkeypatch):
    assert themes.available()["mine"] == mine
    settings.active["theme_options"] = {"accent": "#ff0000", "bad key!": "x"}
    page = themes.for_page("mine", "es")
    assert page["css"] == "/theme/mine/theme.css" and 'data-block="face"' in page["html"]
    assert page["options"] == {"accent": "#ff0000"}  # yours win; odd names are dropped


def test_unknown_theme_falls_back_to_eyes(mine):
    assert themes.for_page("nope", "es")["name"] == "eyes"


def test_texts_override_only_the_screen(mine):
    (mine / "locales").mkdir()
    (mine / "locales" / "en.json").write_text(json.dumps({"ui": {"thinking": "Hmm"}, "theme": {"hello": "Hi"}}))
    (mine / "locales" / "es.json").write_text(json.dumps({"ui": {"thinking": "Mmm…"}, "speech": {"wait": "x"}}))
    page = themes.for_page("mine", "es")
    assert page["ui"] == {"thinking": "Mmm…"} and page["texts"] == {"hello": "Hi"}
    assert any("speech" in p for p in themes.check(mine))  # what it says isn't a theme's business


def test_files_only_from_inside_the_theme(mine):
    (mine / "images").mkdir()
    (mine / "images" / "a.png").write_bytes(b"png")
    assert themes.asset("mine", "images/a.png") == (mine / "images" / "a.png").resolve()
    assert themes.asset("mine", "../../permissions.json") is None
    assert themes.asset("mine", "theme.html") is None  # not a kind it serves
    assert themes.asset("nope", "theme.css") is None


def test_what_is_wrong_in_a_theme(mine):
    (mine / "theme.css").write_text("@import url(https://fonts.example/x.css);")
    (mine / "theme.html").write_text('<div data-block="faces" onclick="x()"></div>')
    problems = " ".join(themes.check(mine))
    for words in ("outside resources", "unknown block «faces»", "onclick"):
        assert words in problems, words


def test_new_theme_from_another(mine):
    created = themes.new("lamp", "bedside")
    assert json.loads((created / "theme.json").read_text())["based_on"] == "bedside"
    assert "lamp" in themes.available()
    with pytest.raises(ValueError):
        themes.new("lamp", "bedside")
    with pytest.raises(ValueError):
        themes.new("../evil", "eyes")


def test_sounds(mine):
    assert themes.sound("eyes", "wake") is None  # the plugin «sounds»'s, then
    bedside = themes.sound("bedside", "alarm")
    assert bedside is not None and bedside.dtype.name == "int16" and len(bedside) > 48000


def test_the_page_forbids_outside_resources_and_scripts():
    import asyncio

    import web

    async def handler(request):
        from aiohttp import web
        return web.Response(text="x")

    request = type("Request", (), {"path": "/"})()
    response = asyncio.run(web.no_cache(request, handler))
    policy = response.headers["Content-Security-Policy"]
    assert "script-src 'self'" in policy and "default-src 'self'" in policy


def test_jarvis_makes_a_theme_of_your_own(mine, monkeypatch):
    import tools

    assert "Created" in tools.call("create_theme", {"name": "lamp", "based_on": "orb"})
    assert "=== theme.css ===" in tools.call("get_theme", {"name": "lamp"})
    css = "body[data-look=\"thinking\"] .core { background: #ff00ff; }"
    assert tools.call("edit_theme", {"name": "lamp", "file": "theme.css", "content": css}).startswith("Saved.")
    assert (mine.parent / "lamp" / "theme.css").read_text() == css
    answer = tools.call("edit_theme", {"name": "lamp", "file": "theme.html", "content": '<p data-block="faces"></p>'})
    assert "unknown block «faces»" in answer  # what is wrong, for it to fix
    tools.call("edit_theme", {"name": "lamp", "file": "theme.html", "content": '<div data-block="face"></div>'})
    tools.call("edit_theme", {"name": "lamp", "file": "locales/es.json", "content": '{"ui": {"thinking": "Mmm"}}'})
    assert themes.for_page("lamp", "es")["ui"] == {"thinking": "Mmm"}
    tools.call("delete_theme", {"name": "lamp"})
    assert "lamp" not in themes.available()


@pytest.mark.parametrize("arguments", [
    {"name": "eyes", "file": "theme.css", "content": "x"},  # a system theme
    {"name": "mine", "file": "../evil.css", "content": "x"},
    {"name": "mine", "file": "sounds/wake.wav", "content": "x"},
    {"name": "mine", "file": "theme.json", "content": "not json"},
    {"name": "mine", "file": "theme.css", "content": "x" * 200_000},
    {"name": "nope", "file": "theme.css", "content": "x"},
])
def test_what_it_cant_edit(mine, arguments):
    import tools

    with pytest.raises(tools.ToolError):
        tools.call("edit_theme", arguments)


def test_system_themes_cant_be_deleted_and_yours_need_a_yes(mine):
    import tools

    with pytest.raises(tools.ToolError):
        tools.call("delete_theme", {"name": "eyes"})
    assert "delete_theme" in tools.NEEDS_YES and "edit_theme" not in tools.NEEDS_YES


def test_a_themes_description_in_the_servers_language():
    from plugins.page import themes

    assert themes.description("eyes", "es").startswith("Dos ojos azules")
    assert themes.description("eyes", "en").startswith("Two blue robot eyes")  # theme.json's
