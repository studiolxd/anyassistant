"""The camera monitor: /monitor (a page) and /video.mjpg (the device's camera as MJPEG,
10 frames a second), for the Mac's browser; paired devices only, like the rest."""

import asyncio
from pathlib import Path

from aiohttp import web as http

import hub
import web

HERE = Path(__file__).parent


@web.route("GET", "/monitor")
async def _monitor(request):
    return web.page(HERE / "monitor.html")


@web.route("GET", "/video.mjpg")
async def _video(request):
    """What the camera sees, to watch it from the Mac's browser."""
    if refusal := web.refused(request):
        return refusal
    response = http.StreamResponse(headers={"Content-Type": "multipart/x-mixed-replace; boundary=frame"})
    await response.prepare(request)
    while True:
        session = hub.current()
        image = session.jpeg() if session else None
        if image:
            await response.write(b"--frame\r\nContent-Type: image/jpeg\r\n\r\n" + image + b"\r\n")
        await asyncio.sleep(1 / 10)
