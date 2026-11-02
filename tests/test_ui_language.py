"""The interface's language (web.ui_language, i18n.choose/ui): each device or browser chooses the
language of its page and its app's face, apart from the one the assistant speaks (i18n.L)."""

import asyncio
import json

import pytest
from aiohttp.test_utils import make_mocked_request

import i18n
import kernel
import settings
import web

page = kernel.load("page")
admin = kernel.load("admin")
devices = None  # the plugin as the server finds it (kernel.module), for each test


@pytest.fixture(autouse=True)
def isolated(tmp_path, monkeypatch):
    global devices
    devices = kernel.load("devices")
    monkeypatch.setattr(devices, "FILE", tmp_path / "devices.json")
    monkeypatch.setattr(admin, "FILE", tmp_path / "admins.json")
    monkeypatch.setattr(settings, "active", {"plugins": {"devices": True, "pairing": False}, "port": 8080, "name": "Eva"})
    monkeypatch.setattr(web, "identity", lambda: "3f2a")


def request(path="/config", accept=None, cookie=None, remote="192.168.1.50", body=None, method="GET"):
    headers = {"User-Agent": "Mozilla/5.0 (iPad; CPU OS 15_8 like Mac OS X) Mobile/15E148", "Host": "192.168.1.40:8080"}
    if accept:
        headers["Accept-Language"] = accept
    if cookie:
        headers["Cookie"] = cookie
    made = make_mocked_request(method, path, headers=headers,
                               transport=type("T", (), {"get_extra_info": lambda self, k, d=None:
                                                        (remote, 1) if k == "peername" else d})())
    if body is not None:
        async def read_json():
            return body
        made.json = read_json
    return made


def config(**kw) -> dict:
    return json.loads(asyncio.run(page._config(request(**kw))).body)


def test_there_are_interface_texts_in_english_and_spanish():
    assert {"en", "es"} <= set(i18n.interface_languages())


@pytest.mark.parametrize("chosen, accept, expected", [
    ("es", "en-US,en;q=0.9", "es"),  # a choice wins over the browser's
    (None, "es-ES,es;q=0.9,en;q=0.8", "es"),  # the browser's
    (None, "fr-FR,fr;q=0.9,en;q=0.5,es;q=0.8", "es"),  # its first with texts, by weight
    (None, "fr-FR", "en"),  # none with texts: the assistant's (English here)
    ("auto", "", "en"),
    ("xx", "es", "es"),  # a choice without texts counts as none
])
def test_choosing_the_interfaces_language(en, chosen, accept, expected):
    assert i18n.choose(chosen, accept) == expected


def test_with_nothing_said_the_interface_is_in_the_assistants_language(es):
    assert i18n.choose(None, "") == "es"
    assert i18n.choose(None, "de-DE") == "es"


def test_another_languages_texts_alongside_the_assistants(es):
    english = i18n.ui("en")
    assert english.code == "en" and english.data["ui"]["asleep"] != i18n.L.data["ui"]["asleep"]
    assert i18n.ui("es") is i18n.L  # the assistant's own
    assert i18n.L.code == "es"  # untouched


def test_the_page_follows_the_browser_not_the_assistant(es):
    found = config(accept="en-US,en;q=0.9")
    assert found["lang"] == "en" and found["ui"]["asleep"] == i18n.ui("en").data["ui"]["asleep"]
    assert found["wake_phrase"] == "Ey, Eva"  # what you say to it: the assistant's language
    assert found["ui_language"] == "auto"


def test_ui_in_the_query_wins(en):
    found = config(path="/config?ui=es", accept="en")
    assert found["lang"] == "es" and found["ui"]["asleep"] == i18n.ui("es").data["ui"]["asleep"]


def test_a_cookie_wins_over_accept_language(en):
    assert config(cookie=f"{web.UI_COOKIE}=es", accept="en")["lang"] == "es"
    assert config(cookie=f"{web.UI_COOKIE}=auto", accept="es")["lang"] == "es"  # auto: the browser's


def test_a_devices_own_language_wins_over_its_browser(en):
    devices.set_ui_language("tablet1", "es")
    found = config(path="/config?device=tablet1", accept="en", cookie=f"{web.UI_COOKIE}=en")
    assert found["lang"] == "es" and found["ui_language"] == "es"
    assert config(path="/config?device=other", accept="en")["lang"] == "en"  # another device: its own
    assert config(path="/config?device=tablet1&ui=en")["lang"] == "en"  # an app's explicit ?ui=


def test_a_devices_language_back_to_automatic(en):
    devices.set_ui_language("tablet1", "es")
    devices.set_ui_language("tablet1", "auto")
    assert devices.ui_language("tablet1") == "" and "ui_language" not in devices.load()["tablet1"]
    assert config(path="/config?device=tablet1", accept="es")["lang"] == "es"


def test_only_languages_with_interface_texts(en):
    with pytest.raises(ValueError):
        devices.set_ui_language("tablet1", "fr")


def test_set_from_devices_by_the_owner_and_listed(en):
    devices.change("tablet1", "iPad", "Cocina")
    answer = asyncio.run(devices._change(request("/devices", method="POST", remote="127.0.0.1",
                                                 body={"id": "tablet1", "ui_language": "es"})))
    listed = json.loads(answer.body)
    assert listed["devices"][0]["ui_language"] == "es" and listed["ui_languages"]["es"] == "Español"
    refused = asyncio.run(devices._change(request("/devices", method="POST", body={"id": "tablet1", "ui_language": "en"})))
    assert refused.status == 403 and devices.ui_language("tablet1") == "es"  # another device isn't the owner
    wrong = asyncio.run(devices._change(request("/devices", method="POST", remote="127.0.0.1",
                                                body={"id": "tablet1", "ui_language": "fr"})))
    assert wrong.status == 400


def test_a_device_sets_its_own_from_its_app(en):
    answer = asyncio.run(devices._own_ui_language(request("/devices/ui_language", method="POST",
                                                          body={"device": "phone-1", "ui_language": "es"})))
    assert json.loads(answer.body) == {"ui_language": "es"}
    assert devices.load()["phone-1"]["name"] == "iPad"  # not seen yet: added with its kind's name
    bad = asyncio.run(devices._own_ui_language(request("/devices/ui_language", method="POST",
                                                       body={"device": "../x", "ui_language": "es"})))
    assert bad.status == 400


def test_a_device_on_screen_reads_its_texts_again(en, monkeypatch):
    import hub

    class Session:
        device, sent = "tablet1", []
        pc = type("PC", (), {"connectionState": "connected"})()

        def send(self, data):
            self.sent.append(data)

    session = Session()
    monkeypatch.setattr(hub, "all", lambda: [session])
    devices.set_ui_language("tablet1", "es")
    assert session.sent == [{"type": "config"}]


def test_the_connect_page_in_the_browsers_language(es):
    body = asyncio.run(page._connect(request("/connect?code=482913", accept="en-GB,en"))).text
    assert 'lang="en"' in body and "Open in the app" in body
    body = asyncio.run(page._connect(request("/connect?code=482913", cookie=f"{web.UI_COOKIE}=es", accept="en"))).text
    assert 'lang="es"' in body


def test_the_admin_texts_follow_the_browsers_cookie(en):
    me = json.loads(asyncio.run(admin._me(request("/admin/me", cookie=f"{web.UI_COOKIE}=es"))).body)
    assert me["lang"] == "es" and me["ui_language"] == "es" and me["ui_languages"] == {"en": "English", "es": "Español"}
    assert me["texts"] == i18n.ui("es").data["admin_page"]
    plain = json.loads(asyncio.run(admin._me(request("/admin/me", accept="en"))).body)
    assert plain["lang"] == "en" and plain["ui_language"] == "auto"


def test_the_admin_settings_in_the_interfaces_language(en):
    found = json.loads(asyncio.run(admin._settings(request("/admin/settings?ui=es", remote="127.0.0.1"))).body)
    title = {o["name"]: o["title"] for o in found["options"]}["language"]
    assert title == i18n.ui("es").text("options_title.language")
    assert i18n.L.code == "en"


def test_the_pages_declare_their_language_from_the_start(en):
    response = web.page(page.WEB / "index.html", request("/", cookie=f"{web.UI_COOKIE}=es"))
    assert '<html lang="es"' in response.text
