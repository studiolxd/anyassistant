"""The plugin «bonjour»: what the announcement says."""

import kernel
import settings


def test_the_record_says_the_name_and_whether_to_pair(monkeypatch):
    bonjour = kernel.load("bonjour")
    monkeypatch.setattr(bonjour, "address", lambda: None)
    monkeypatch.setattr(settings, "active", {"name": "Viernes", "plugins": {"pairing": True}})
    assert bonjour.record() == ["name=Viernes", "pairing=1", "version=1"]
    monkeypatch.setattr(settings, "active", {})
    assert bonjour.record() == ["name=Jarvis", "pairing=0", "version=1"]


def test_and_its_address_now(monkeypatch):
    """An app that knew another IP (the Mac's changed) finds the new one in the announcement."""
    bonjour = kernel.load("bonjour")
    monkeypatch.setattr(bonjour, "address", lambda: "192.168.1.40")
    monkeypatch.setattr(settings, "active", {})
    assert "address=192.168.1.40" in bonjour.record()


def test_it_is_announced_again_when_its_address_changes(monkeypatch):
    import asyncio

    import web

    bonjour = kernel.load("bonjour")
    monkeypatch.setattr(settings, "active", {})
    monkeypatch.setattr(bonjour, "CHECK", 0.01)
    monkeypatch.setattr(web, "close_on_exit", [])
    addresses, announced, withdrawn = iter(["192.168.1.40", "192.168.1.40", "192.168.1.77"]), [], []
    monkeypatch.setattr(bonjour, "address", lambda: next(addresses, "192.168.1.77"))

    async def announce(ip):
        announced.append(ip)

        async def stop():
            withdrawn.append(ip)
        return stop

    monkeypatch.setattr(bonjour, "_announce", announce)

    async def run():
        await bonjour.announce(None)
        await asyncio.sleep(0.1)
        for stop in web.close_on_exit:
            await stop()

    asyncio.run(run())
    assert announced == ["192.168.1.40", "192.168.1.77"]  # once per address, not every check
    assert withdrawn == ["192.168.1.40", "192.168.1.77"]  # the old one withdrawn; the last, when it stops
