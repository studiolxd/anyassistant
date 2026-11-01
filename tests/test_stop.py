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
