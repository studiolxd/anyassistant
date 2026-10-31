"""The plugin «bonjour»: what the announcement says."""

import kernel
import settings


def test_the_record_says_the_name_and_whether_to_pair(monkeypatch):
    bonjour = kernel.load("bonjour")
    monkeypatch.setattr(settings, "active", {"name": "Viernes", "plugins": {"pairing": True}})
    assert bonjour.record() == ["name=Viernes", "pairing=1", "version=1"]
    monkeypatch.setattr(settings, "active", {})
    assert bonjour.record() == ["name=Jarvis", "pairing=0", "version=1"]
