"""The skins lab: /lab?skin=<name> shows every state of a skin at once (each one the
page in ?demo=<state>), reloading when its files change. Its page, script and
styles are here."""

from pathlib import Path

from aiohttp import web as http

import web

HERE = Path(__file__).parent
FILES = {"lab.js", "lab.css"}


@web.route("GET", "/lab")
async def _lab(request):
    return web.page(HERE / "lab.html")


@web.route("GET", "/lab/{file}")
async def _file(request):
    name = request.match_info["file"]
    return http.FileResponse(HERE / name) if name in FILES else http.Response(status=404)
