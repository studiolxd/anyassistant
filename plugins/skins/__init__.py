"""The skins: /skins?skin=<name> shows every state of a skin at once (each one the page in
?demo=<state>), to see them and choose; it reloads when its files change. The Mac app opens it
(its menu: «Skins…»). Only to look: skins are edited elsewhere (your folder, or by voice).
Its page, script and styles are here."""

from pathlib import Path

from aiohttp import web as http

import web

HERE = Path(__file__).parent
FILES = {"skins.js", "skins.css"}


@web.route("GET", "/skins")
async def _skins(request):
    return web.page(HERE / "skins.html")


@web.route("GET", "/skins/{file}")
async def _file(request):
    name = request.match_info["file"]
    return http.FileResponse(HERE / name) if name in FILES else http.Response(status=404)
