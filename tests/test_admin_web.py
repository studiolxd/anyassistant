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
