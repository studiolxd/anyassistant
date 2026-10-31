import time

import pytest

import kernel
import settings
import web

pairing = None


class Request:
    def __init__(self, remote, token=None):
        self.remote, self.cookies = remote, ({pairing.COOKIE: token} if token else {})


@pytest.fixture(autouse=True)
def plugin():
    """The plugin as loaded now (other tests may have loaded the plugins again)."""
    global pairing
    pairing = kernel.load("pairing")


@pytest.fixture
def on(tmp_path, monkeypatch):
    monkeypatch.setattr(pairing, "FILE", tmp_path / "paired.json")
    monkeypatch.setattr(settings, "active", {"plugins": {"pairing": True}})
    monkeypatch.setattr(pairing, "_code", {})


def test_off_by_default_lets_everyone_in(monkeypatch):
    monkeypatch.setattr(settings, "active", {})
    assert not kernel.enabled("pairing")
    assert web.refused(Request("192.168.1.50")) is None


def test_on_the_web_server_refuses_strangers(on):
    assert web.refused(Request("192.168.1.50")).status == 403
    assert web.refused(Request("127.0.0.1")) is None
    token = pairing.pair(pairing.new_code(), "Tablet")
    assert web.refused(Request("192.168.1.50", token)) is None


def test_the_mac_itself_always(on):
    assert pairing.allowed("127.0.0.1", None)
    assert not pairing.allowed("192.168.1.50", None)
    assert not pairing.allowed("192.168.1.50", "made-up")


def test_a_code_pairs_one_device(on):
    code = pairing.new_code()
    assert len(code) == 6 and code.isdigit()
    token = pairing.pair(code, "Tablet")
    assert token and pairing.allowed("192.168.1.50", token)
    assert pairing.pair(code, "Another") is None
    assert token not in pairing.FILE.read_text()  # only its hash


def test_wrong_attempts_burn_the_code(on):
    code = pairing.new_code()
    wrong = "000000" if code != "000000" else "111111"
    for _ in range(pairing.CODE_ATTEMPTS):
        assert pairing.pair(wrong, "x") is None
    assert pairing.pair(code, "x") is None


def test_codes_expire(on):
    code = pairing.new_code()
    pairing._code["until"] = time.time() - 1
    assert pairing.pair(code, "x") is None


def test_unpair_all(on):
    token = pairing.pair(pairing.new_code(), "Tablet")
    pairing.unpair_all()
    assert not pairing.allowed("192.168.1.50", token)
