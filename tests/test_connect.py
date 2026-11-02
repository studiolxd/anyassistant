"""The QR's page (plugin «page», /connect): what the QR in «Conectar otro dispositivo» opens."""

import asyncio
import time

import pytest
from aiohttp import web as http
from aiohttp.test_utils import make_mocked_request

import kernel
import settings
import web

page = kernel.load("page")
PHONE = "Mozilla/5.0 (iPhone; CPU iPhone OS 15_8 like Mac OS X) AppleWebKit/605.1.15 Mobile/15E148 Safari/604.1"
ANDROID = "Mozilla/5.0 (Linux; Android 9; Tablet) AppleWebKit/537.36 Chrome/81.0 Safari/537.36"
LAPTOP = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) Firefox/130.0"


@pytest.fixture
def pairing(tmp_path, monkeypatch):
    found = kernel.load("pairing")
    monkeypatch.setattr(found, "FILE", tmp_path / "paired.json")
    monkeypatch.setattr(found, "_code", {})
    monkeypatch.setattr(settings, "active", {"plugins": {"pairing": True}, "port": 8080, "name": "Eva"})
    monkeypatch.setattr(web, "identity", lambda: "3f2a")
    return found


@pytest.fixture
def off(monkeypatch):
    monkeypatch.setattr(settings, "active", {"plugins": {"pairing": False}, "port": 8080, "name": "Eva"})
    monkeypatch.setattr(web, "identity", lambda: "3f2a")


def request(method="GET", path="/connect", agent=LAPTOP, cookie=None, form=None, remote="192.168.1.50",
            host="192.168.1.40:8080"):
    headers = {"User-Agent": agent, "Host": host}
    if cookie:
        headers["Cookie"] = cookie
    made = make_mocked_request(method, path, headers=headers,
                               transport=type("T", (), {"get_extra_info": lambda self, k, d=None:
                                                        (remote, 1) if k == "peername" else d})())
    if form is not None:
        async def post():
            return form
        made.post = post
    return made


def get(**kw):
    return asyncio.run(page._connect(request(**kw)))


def post(**kw):
    return asyncio.run(page._connect_pair(request("POST", **kw)))


def test_the_qr_says_the_server_by_its_address_now_with_the_code():
    assert page.connect_url("192.168.1.40", 8080, "482913") == "http://192.168.1.40:8080/connect?code=482913"
    assert page.connect_url("192.168.1.40", 8080) == "http://192.168.1.40:8080/connect"  # pairing off: no code
    assert page.connect_url("10.0.0.2", 9000, "000001").startswith("http://")  # plain HTTP even with «https»: it works before the certificate


def test_the_apps_link_carries_everything_to_pair_with_nothing_to_type():
    link = page.app_url("192.168.1.40", 8080, "482913", "3f2a", "Eva")
    assert link == "anyassistant://connect?host=192.168.1.40&port=8080&code=482913&server=3f2a&name=Eva"
    assert "code" not in page.app_url("192.168.1.40", 8080, None, "3f2a", "Eva")


def test_a_good_code_pairs_the_browser_and_sends_it_on(pairing):
    code = pairing.new_code()
    answer = post(form={"code": code}, agent=PHONE)
    assert answer.status == 302 and answer.headers["Location"] == "/connect"
    token = answer.cookies[pairing.COOKIE].value
    assert pairing.allowed("192.168.1.50", token)
    # Paired, no HTTPS: a laptop goes straight to the page; a phone still sees «Abrir en la app».
    with pytest.raises(http.HTTPFound) as sent:
        get(cookie=f"{pairing.COOKIE}={token}")
    assert sent.value.location == "/"
    body = get(cookie=f"{pairing.COOKIE}={token}", agent=PHONE).text
    assert "anyassistant://connect?host=192.168.1.40&amp;port=8080&amp;server=3f2a&amp;name=Eva" in body
    assert 'href="/"' in body and "<form" not in body


def test_a_wrong_or_expired_code_shows_the_form_again_with_the_reason(pairing):
    code = pairing.new_code()
    wrong = "000000" if code != "000000" else "111111"
    answer = post(form={"code": wrong})
    assert answer.status == 200 and "Wrong or expired" in answer.text and "<form" in answer.text
    assert pairing.COOKIE not in answer.cookies
    pairing._code["until"] = time.time() - 1
    assert "Wrong or expired" in post(form={"code": code}).text


def test_the_qr_opened_on_a_phone_offers_the_app_with_the_code_or_the_browser(pairing):
    body = get(path="/connect?code=482913", agent=PHONE).text
    assert "anyassistant://connect?host=192.168.1.40&amp;port=8080&amp;code=482913&amp;server=3f2a&amp;name=Eva" in body
    assert 'value="482913"' in body and "Continue in the browser" in body
    laptop = get(path="/connect?code=482913").text
    assert "anyassistant://" not in laptop and ">Connect<" in laptop  # no app for a laptop: the code, in the browser


def test_on_android_the_link_falls_back_to_this_page_without_the_app(pairing):
    body = get(path="/connect?code=482913", agent=ANDROID).text
    assert "intent://connect?host=192.168.1.40&amp;port=8080&amp;code=482913" in body
    assert "scheme=anyassistant;package=com.anyassistant;S.browser_fallback_url=http%3A%2F%2F192.168.1.40%3A8080%2Fconnect%3Fcode%3D482913;end" in body


def test_with_pairing_off_no_code_is_needed(off):
    with pytest.raises(http.HTTPFound):  # a laptop: the page at once
        get()
    body = get(agent=PHONE).text
    assert "No code needed" in body and "<form" not in body and "anyassistant://connect?host=192.168.1.40" in body
    with pytest.raises(http.HTTPFound):  # the form posted anyway: on to the page, nothing to pair
        post(form={"code": ""})


def test_with_https_the_certificate_comes_first_then_the_https_page(pairing, monkeypatch):
    monkeypatch.setattr(settings, "active", {"plugins": {"pairing": True, "https": True}, "port": 8080, "https_port": 443})
    token = pairing.pair(pairing.new_code(), "Tablet")
    body = get(cookie=f"{pairing.COOKIE}={token}", agent=ANDROID).text
    assert "First, install the certificate" in body and 'href="/https/ca.crt"' in body
    assert 'href="https://192.168.1.40/"' in body
    laptop = get(cookie=f"{pairing.COOKIE}={token}").text  # a laptop needs the certificate too
    assert 'href="/https/ca.crt"' in laptop


def test_the_page_is_in_the_servers_language(pairing, es):
    body = get(path="/connect?code=482913", agent=PHONE).text
    assert 'lang="es"' in body and "Abrir en la app" in body and "Continuar en el navegador" in body


def test_the_admin_status_gives_what_the_qr_and_the_addresses_need(monkeypatch):
    admin = kernel.load("admin")
    monkeypatch.setattr(settings, "active", {"plugins": {"https": False}, "port": 8080})
    monkeypatch.setattr(admin, "_addresses", lambda: ["192.168.1.40"])
    import json
    found = json.loads(asyncio.run(admin._status(request(path="/admin/status", remote="127.0.0.1"))).body)
    assert found["connect"] == "http://192.168.1.40:8080/connect"
    assert found["local"] == "http://anyassistant.local:8080" and found["address"] == "192.168.1.40"
    assert found["certificate"] is None and found["pairing"] is False
    monkeypatch.setattr(settings, "active", {"plugins": {"https": True, "pairing": True}, "port": 8080})
    found = json.loads(asyncio.run(admin._status(request(path="/admin/status", remote="127.0.0.1"))).body)
    assert found["certificate"] == "http://192.168.1.40:8080/https/ca.crt" and found["pairing"] is True


def test_the_address_shown_is_the_one_that_reaches_the_network(monkeypatch):
    """With HTTPS on, every address of the computer is known; the QR's is the routed one, and a
    self-assigned 169.254… (no router) never goes first."""
    admin = kernel.load("admin")
    import socket
    import types

    class Probe:
        def __init__(self, *a):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def connect(self, where):
            pass

        def getsockname(self):
            return ("192.168.1.130", 5000)

    monkeypatch.setattr(socket, "socket", Probe)
    https = types.SimpleNamespace(addresses=lambda: ["127.0.0.1", "169.254.122.127", "192.168.1.130", "10.0.0.5"])
    monkeypatch.setattr(kernel, "module", lambda name: https if name == "https" else None)
    assert admin._addresses() == ["192.168.1.130", "10.0.0.5", "169.254.122.127"]
