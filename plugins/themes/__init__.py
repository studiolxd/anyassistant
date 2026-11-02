"""The themes: /themes?theme=<name> shows every state of a theme at once (each one the page in
?demo=<state>), to see them and choose; it reloads when its files change. The Mac app opens it
(its menu: «Themes…»). Only to look: themes are edited elsewhere (your folder, or by voice).
Its page, script and styles are here."""

from pathlib import Path

from aiohttp import web as http

import web

HERE = Path(__file__).parent
FILES = {"themes.js", "themes.css"}


@web.route("GET", "/themes")
async def _themes(request):
    return web.page(HERE / "themes.html", request)


@web.route("GET", "/themes/{file}")
async def _file(request):
    name = request.match_info["file"]
    return http.FileResponse(HERE / name) if name in FILES else http.Response(status=404)
