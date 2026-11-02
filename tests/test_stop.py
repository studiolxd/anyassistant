"""Stopping and restarting the server from inside (web.stop): no signals, so Windows too."""

import asyncio

import pytest
from aiohttp import web as aiohttp_web

import web


def test_stop_gets_out_of_the_loop_and_says_whether_to_restart(monkeypatch):
    monkeypatch.setattr(web, "restarting", False)

    async def running():
        web.stop(restart=True)
        await asyncio.sleep(5)  # it never gets here

    with pytest.raises(aiohttp_web.GracefulExit):
        asyncio.run(running())
    assert web.restarting


class Gone(Exception):
    pass


def test_started_by_the_desktop_app_it_ends_with_the_code_it_asked_for(monkeypatch):
    """Windows: os.execv would be another process, out of the app's sight; the app starts it again."""
    import main

    ended, replaced = [], []
    monkeypatch.setenv("ANYASSISTANT_RESTART_EXIT", "75")
    monkeypatch.setattr(main.os, "_exit", lambda code: (ended.append(code), (_ for _ in ()).throw(Gone()))[1])
    monkeypatch.setattr(main.os, "execv", lambda *a: replaced.append(a))
    with pytest.raises(Gone):
        main.start_again(["server/main.py"])
    assert ended == [75] and not replaced


def test_otherwise_it_replaces_itself(monkeypatch):
    """macOS and Linux (the Mac app, systemd, bin/anyassistant): the same process again, same options."""
    import main

    replaced = []
    monkeypatch.delenv("ANYASSISTANT_RESTART_EXIT", raising=False)
    monkeypatch.setattr(main.os, "_exit", lambda code: pytest.fail("it shouldn't end"))
    monkeypatch.setattr(main.os, "execv", lambda path, argv: replaced.append(argv))
    monkeypatch.setattr(main.settings, "load", lambda: {})
    main.start_again(["server/main.py", "--port", "8081"])
    assert replaced and replaced[0][1:] == ["server/main.py", "--port", "8081"]
