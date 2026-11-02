"""The admin page (plugin «admin»): from this computer, or a browser given an admin code."""

import asyncio
import json

import pytest
from aiohttp.test_utils import make_mocked_request

import kernel
import web

admin = kernel.load("admin")


@pytest.fixture(autouse=True)
def isolated_admins(tmp_path, monkeypatch):
    monkeypatch.setattr(admin, "FILE", tmp_path / "admins.json")
    monkeypatch.setattr(admin, "_code", {})


def request(method="GET", path="/admin/settings", remote="192.168.1.50", cookie=None, body=None):
    headers = {"User-Agent": "Firefox on the laptop"}
    if cookie:
        headers["Cookie"] = f"{admin.COOKIE}={cookie}"
    made = make_mocked_request(method, path, headers=headers,
                               transport=type("T", (), {"get_extra_info": lambda self, k, d=None:
                                                        (remote, 1) if k == "peername" else d})())
    if body is not None:
        async def read_json():
            return body
        made.json = read_json
    return made


def test_this_computer_is_the_owner_and_others_are_not():
    assert web.owner(request(remote="127.0.0.1"))
    assert not web.owner(request())
    answer = asyncio.run(admin._settings(request()))
    assert answer.status == 403 and json.loads(answer.body) == {"owner": False}


def test_a_code_makes_a_browser_the_owner_once():
    code = admin.new_code()
    wrong = asyncio.run(admin._login(request("POST", "/admin/login", body={"code": "000000" if code != "000000" else "1"})))
    assert wrong.status == 403
    right = asyncio.run(admin._login(request("POST", "/admin/login", body={"code": code})))
    assert right.status == 200
    token = right.cookies[admin.COOKIE].value
    assert right.cookies[admin.COOKIE]["httponly"] and right.cookies[admin.COOKIE]["samesite"] == "Strict"
    assert web.owner(request(cookie=token))
    assert not web.owner(request(cookie="made-up"))
    again = asyncio.run(admin._login(request("POST", "/admin/login", body={"code": code})))
    assert again.status == 403  # one browser per code
    assert admin.FILE.read_text().count("hash") == 1 and token not in admin.FILE.read_text()  # only its hash


def test_too_many_wrong_codes_and_the_code_is_gone():
    code = admin.new_code()
    for _ in range(admin.CODE_ATTEMPTS):
        admin.login("999999" if code != "999999" else "111111", "x")
    assert admin.login(code, "x") is None


def test_revoking_a_browser():
    token = admin.login(admin.new_code(), "the laptop")
    listed = json.loads(asyncio.run(admin._admins(request(cookie=token))).body)["admins"]
    assert listed[0]["you"] and listed[0]["name"] == "the laptop"
    asyncio.run(admin._change_admins(request("POST", cookie=token, body={"logout": True})))
    assert not web.owner(request(cookie=token))


def test_the_page_and_its_texts_are_for_anyone_the_data_only_for_the_owner():
    assert asyncio.run(admin._page(request(path="/admin"))).status == 200
    me = json.loads(asyncio.run(admin._me(request(path="/admin/me"))).body)
    assert me["owner"] is False and "texts" in me


def test_the_qr_is_an_svg():
    answer = asyncio.run(admin._qr(request(path="/admin/qr?text=http://anyassistant.local:8080", remote="127.0.0.1")))
    assert answer.content_type == "image/svg+xml" and b"<svg" in answer.body


def test_an_api_key_goes_to_the_keychain_never_to_the_file(monkeypatch, tmp_path):
    import keychain
    import settings

    kernel.load("llm-openai")
    stored = {}
    monkeypatch.setattr(keychain, "put", lambda service, account, secret: stored.update({account: secret}))
    monkeypatch.setattr(keychain, "forget", lambda service, account: stored.pop(account, None))
    monkeypatch.setattr(keychain, "get", lambda service, account: stored.get(account))
    monkeypatch.setattr(settings, "PATH", tmp_path / "settings.json")
    monkeypatch.setattr(settings, "refresh", lambda: set())
    asyncio.run(admin._save_settings(request("POST", remote="127.0.0.1", body={"openai_key": " sk-test "})))
    assert stored == {"openai": "sk-test"}
    assert "sk-test" not in (tmp_path / "settings.json").read_text()
    listed = json.loads(asyncio.run(admin._settings(request(remote="127.0.0.1"))).text)
    key = next(o for o in listed["options"] if o["name"] == "openai_key")
    assert key["value"] is None and key["set"] is True  # it says it has one, never which
    asyncio.run(admin._save_settings(request("POST", remote="127.0.0.1", body={"openai_key": None})))
    assert stored == {}


# --- Its texts: in both languages, and the Spanish the Mac app's where it says the same thing ---

from pathlib import Path
import re

ROOT = Path(__file__).resolve().parent.parent
MAC_STRINGS = ROOT / "apps/mac/Resources/es.lproj/Localizable.strings"
DESKTOP = ROOT / "apps/desktop"


def mac_spanish() -> dict:
    """The Mac app's Spanish: {English key: Spanish}, with %s for its %@ and %d."""
    found = re.findall(r'^"((?:[^"\\]|\\.)*)"\s*=\s*"((?:[^"\\]|\\.)*)";', MAC_STRINGS.read_text(), re.M)
    return {k.replace('\\"', '"'): re.sub(r"%[@d]", "%s", v.replace('\\"', '"')) for k, v in found}


def keys_in(source: str) -> set:
    """The texts a page asks for: T('…'), M('…') and data-t="…"."""
    found = {k.replace("\\'", "'") for k in re.findall(r"\b[TM]\('((?:[^'\\]|\\.)*)'", source)}
    found |= set(re.findall(r'data-t="([^"]*)"', source))
    return found


ADMIN_INDIRECT = {"Features", "Skills", "Libraries", "Brain", "LLMs", "Speech recognition", "Voices", "Wake word",
                  "Voice detection", "Quiet", "Some noise", "Noisy", "OpenAI-compatible", "Settings", "Devices",
                  "Pair a device", "Admin"}  # asked for through a table (KINDS, the noise levels, the window's title)


def test_the_admin_pages_texts_are_in_both_languages():
    used = keys_in((admin.WEB / "admin.js").read_text()) | ADMIN_INDIRECT
    for language in ("en", "es"):
        texts = json.loads((ROOT / "plugins/admin/locales" / f"{language}.json").read_text())["admin_page"]
        assert used <= texts.keys(), f"{language}: {used - texts.keys()}"
        assert texts.keys() <= used, f"{language}, not used: {texts.keys() - used}"


def test_the_admin_pages_spanish_is_the_macs():
    """Where the page says the same thing as the Mac app (the same English key), it says it the same way."""
    web = json.loads((ROOT / "plugins/admin/locales/es.json").read_text())["admin_page"]
    mac = mac_spanish()
    different = {k: (web[k], mac[k]) for k in web if k in mac and re.sub(r"%d", "%s", web[k]) != mac[k]}
    assert not different


def test_the_desktop_apps_texts_are_in_spanish_and_the_macs():
    """The Windows and Linux app: every text it shows has its Spanish, the Mac's where it says the same."""
    used = set()
    for file in ("main.js", "setup.js", "setup.html", "unavailable.html"):
        used |= keys_in((DESKTOP / file).read_text())
    spanish = {k: v for k, v in json.loads((DESKTOP / "locales/es.json").read_text()).items() if k != "_"}
    assert used <= spanish.keys(), used - spanish.keys()
    assert spanish.keys() <= used, spanish.keys() - used
    mac = mac_spanish()
    different = {k: (spanish[k], mac[k]) for k in spanish if k in mac and spanish[k] != mac[k]}
    assert not different
    english = {k: v for k, v in json.loads((DESKTOP / "locales/en.json").read_text()).items() if k != "_"}
    assert english.keys() <= used, english.keys() - used  # only where its English differs from the key


def test_the_admin_page_opens_as_one_of_the_apps_windows():
    """?window=settings|devices|pair: only that part (the Windows and Linux app's windows, as the Mac's)."""
    js = (admin.WEB / "admin.js").read_text()
    assert "get('window')" in js
    assert all(f"'{w}'" in js for w in ("settings", "devices", "pair"))
    assert "body.window header { display: none; }" in (admin.WEB / "admin.css").read_text()
