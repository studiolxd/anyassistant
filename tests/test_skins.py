"""Skins: anyone's HTML and CSS, cleaned and contained; the system's ones; sounds and texts."""

import json

import pytest

import settings
import skins
from conftest import ROOT


@pytest.fixture
def mine(tmp_path, monkeypatch):
    """A skins_dir of your own, with a skin to play with."""
    monkeypatch.setattr(settings, "active", {"skins_dir": str(tmp_path)})
    skin = tmp_path / "mine"
    skin.mkdir()
    (skin / "skin.json").write_text(json.dumps({"name": "Mine", "options": {"accent": "#123456"}}))
    (skin / "skin.html").write_text('<div data-block="face"></div><p data-block="status"></p>')
    (skin / "skin.css").write_text("body { color: red; }")
    return skin


def test_system_skins_are_fine():
    assert {"eyes", "orb", "minimal", "bedside"} <= set(skins.available())
    for name in ("eyes", "orb", "minimal", "bedside"):
        assert skins.check(ROOT / "skins" / name) == [], name


@pytest.mark.parametrize("html, kept, gone", [
    ('<p onclick="steal()">hi</p>', "<p>hi</p>", "onclick"),
    ('<script>fetch("//evil")</script><p>x</p>', "<p>x</p>", "script"),
    ('<img src="https://tracker.example/x.png">', "<img>", "tracker"),
    ('<img src="//tracker.example/x.png">', "<img>", "tracker"),
    ('<a href="javascript:alert(1)">x</a>', "<a>x</a>", "javascript"),
    ('<img src="../../settings.json">', "<img>", "settings"),
    ('<iframe src="x.html"></iframe><p>y</p>', "<p>y</p>", "iframe"),
    ('<div style="background:url(https://x)">z</div>', "<div>z</div>", "url("),
    ('<img src="images/me.png" alt="me">', '<img src="/skin/s/images/me.png" alt="me">', None),
])
def test_cleaning(html, kept, gone):
    cleaned, _ = skins.clean(html, base="/skin/s/")
    assert cleaned == kept
    if gone:
        assert gone not in cleaned


def test_your_skins_and_their_options(mine, monkeypatch):
    assert skins.available()["mine"] == mine
    settings.active["skin_options"] = {"accent": "#ff0000", "bad key!": "x"}
    page = skins.for_page("mine", "es")
    assert page["css"] == "/skin/mine/skin.css" and 'data-block="face"' in page["html"]
    assert page["options"] == {"accent": "#ff0000"}  # yours win; odd names are dropped


def test_unknown_skin_falls_back_to_eyes(mine):
    assert skins.for_page("nope", "es")["name"] == "eyes"


def test_texts_override_only_the_screen(mine):
    (mine / "locales").mkdir()
    (mine / "locales" / "en.json").write_text(json.dumps({"ui": {"thinking": "Hmm"}, "skin": {"hello": "Hi"}}))
    (mine / "locales" / "es.json").write_text(json.dumps({"ui": {"thinking": "Mmm…"}, "speech": {"wait": "x"}}))
    page = skins.for_page("mine", "es")
    assert page["ui"] == {"thinking": "Mmm…"} and page["texts"] == {"hello": "Hi"}
    assert any("speech" in p for p in skins.check(mine))  # what it says isn't a skin's business


def test_files_only_from_inside_the_skin(mine):
    (mine / "images").mkdir()
    (mine / "images" / "a.png").write_bytes(b"png")
    assert skins.asset("mine", "images/a.png") == (mine / "images" / "a.png").resolve()
    assert skins.asset("mine", "../../permissions.json") is None
    assert skins.asset("mine", "skin.html") is None  # not a kind it serves
    assert skins.asset("nope", "skin.css") is None


def test_check_finds_what_the_tablet_lacks(mine):
    (mine / "skin.css").write_text(".a { inset: 0; } .b { display: flex; gap: 4px; } .c:has(p) {} "
                                   "@import url(https://fonts.example/x.css);")
    (mine / "skin.html").write_text('<div data-block="faces" onclick="x()"></div>')
    problems = " ".join(skins.check(mine))
    for words in ("inset", "gap", ":has", "outside resources", "unknown block «faces»", "onclick"):
        assert words in problems, words


def test_new_skin_from_another(mine):
    created = skins.new("lamp", "bedside")
    assert json.loads((created / "skin.json").read_text())["based_on"] == "bedside"
    assert "lamp" in skins.available()
    with pytest.raises(ValueError):
        skins.new("lamp", "bedside")
    with pytest.raises(ValueError):
        skins.new("../evil", "eyes")


def test_sounds(mine):
    assert skins.sound("eyes", "wake") is None  # the system's beeps
    bedside = skins.sound("bedside", "alarm")
    assert bedside is not None and bedside.dtype.name == "int16" and len(bedside) > 48000


def test_the_page_forbids_outside_resources_and_scripts():
    import asyncio

    import main

    async def handler(request):
        from aiohttp import web
        return web.Response(text="x")

    request = type("Request", (), {"path": "/"})()
    response = asyncio.run(main.no_cache(request, handler))
    policy = response.headers["Content-Security-Policy"]
    assert "script-src 'self'" in policy and "default-src 'self'" in policy
