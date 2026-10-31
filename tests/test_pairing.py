import time

import pytest

import pairing
import settings


@pytest.fixture
def on(tmp_path, monkeypatch):
    monkeypatch.setattr(pairing, "FILE", tmp_path / "paired.json")
    monkeypatch.setattr(settings, "active", {"pairing": True})
    monkeypatch.setattr(pairing, "_code", {})


def test_off_lets_everyone_in(monkeypatch):
    monkeypatch.setattr(settings, "active", {})
    assert pairing.allowed("192.168.1.50", None)


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
