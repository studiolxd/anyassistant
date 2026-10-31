"""Jarvis's tools (tools/) as an MCP server, at /mcp on the server itself.

Streamable HTTP, the minimum Claude Code needs: JSON-RPC requests by POST,
answered with plain JSON. Only from the Mac itself: no device on the network,
paired or not, can use it.
"""

import json
import logging

from aiohttp import web as http

import tools
import web

log = logging.getLogger("mcp")
LOCAL = {"127.0.0.1", "::1"}  # only from the Mac itself
NAME = "jarvis"


def _result(id_, result):
    return {"jsonrpc": "2.0", "id": id_, "result": result}


def _error(id_, code, message):
    return {"jsonrpc": "2.0", "id": id_, "error": {"code": code, "message": message}}


def handle(message: dict) -> dict | None:
    """One JSON-RPC message → its answer (None for notifications)."""
    method, id_ = message.get("method"), message.get("id")
    if id_ is None:
        return None  # notifications/initialized and the like
    if method == "initialize":
        version = message.get("params", {}).get("protocolVersion", "2025-06-18")
        return _result(id_, {"protocolVersion": version, "capabilities": {"tools": {}},
                             "serverInfo": {"name": NAME, "version": "1"}})
    if method == "ping":
        return _result(id_, {})
    if method == "tools/list":
        return _result(id_, {"tools": [{"name": name, "description": t.description, "inputSchema": t.schema}
                                       for name, t in tools.available().items()]})
    if method == "tools/call":
        params = message.get("params", {})
        name = params.get("name", "")
        try:
            text, error = tools.call(name, params.get("arguments") or {}), False
            log.info("tool %s", name)
        except tools.ToolError as e:
            text, error = str(e), True
            log.info("tool %s refused: %s", name, e)
        return _result(id_, {"content": [{"type": "text", "text": text}], "isError": error})
    return _error(id_, -32601, f"unknown method {method}")


@web.route("*", "/mcp")
async def endpoint(request: http.Request) -> http.Response:
    if request.remote not in LOCAL:
        return http.Response(status=403)
    if request.method != "POST":
        return http.Response(status=405)  # no server-initiated stream
    try:
        body = await request.json()
    except json.JSONDecodeError:
        return http.json_response(_error(None, -32700, "parse error"), status=400)
    answers = [a for a in map(handle, body if isinstance(body, list) else [body]) if a]
    if not answers:
        return http.Response(status=202)
    return http.json_response(answers if isinstance(body, list) else answers[0])
