"""Claude a través de la CLI de Claude Code: usa tu sesión y tu suscripción, sin API key.

Una conversación es un proceso `claude -p` en modo stream-json: recibe los
mensajes por stdin y devuelve la respuesta a trozos (--include-partial-messages).
Sin herramientas, sin MCP y sin tus ajustes ni CLAUDE.md, para que arranque
rápido y sea solo conversación. Requiere `claude` instalado y con sesión iniciada.
"""

import asyncio
import json
import logging
from pathlib import Path

from llm import INSTRUCCIONES, LLM, ahora, registrar

log = logging.getLogger("llm")

INSTRUCCIONES_CLAUDE = INSTRUCCIONES + """
Cada mensaje empieza con <ahora>…</ahora>, la fecha y hora actuales: úsalas
solo si te preguntan por ellas y no las menciones si no."""

# Un directorio vacío como cwd: así no carga el CLAUDE.md de ningún proyecto.
VACIO = Path(__file__).resolve().parents[2] / ".build" / "claude-vacio"


@registrar("claude")
class Claude(LLM):
    def __init__(self, modelo=None):
        super().__init__(modelo or "sonnet")
        self._proceso = None
        self._turno = asyncio.Lock()

    async def _arrancar(self):
        VACIO.mkdir(parents=True, exist_ok=True)
        self._proceso = await asyncio.create_subprocess_exec(
            "claude", "-p",
            "--input-format", "stream-json",
            "--output-format", "stream-json",
            "--include-partial-messages", "--verbose",
            "--model", self.modelo,
            "--system-prompt", INSTRUCCIONES_CLAUDE,
            "--tools", "",
            "--strict-mcp-config",
            "--setting-sources", "",
            "--no-session-persistence",
            cwd=VACIO,
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            limit=1 << 20,  # algunas líneas de stream-json pasan de los 64 KB por defecto
        )
        asyncio.ensure_future(self._errores(self._proceso))

    async def _errores(self, proceso):
        async for linea in proceso.stderr:
            log.warning("claude: %s", linea.decode().rstrip())

    async def _cerrar(self):
        if self._proceso and self._proceso.returncode is None:
            self._proceso.stdin.close()
            try:
                await asyncio.wait_for(self._proceso.wait(), 2)
            except asyncio.TimeoutError:
                self._proceso.kill()
        self._proceso = None

    async def cerrar(self):
        await self._cerrar()

    async def nueva(self):
        async with self._turno:
            await self._cerrar()
            await self._arrancar()

    async def responder(self, texto: str):
        async with self._turno:
            if not self._proceso or self._proceso.returncode is not None:
                await self._arrancar()
            mensaje = {
                "type": "user",
                "message": {"role": "user", "content": f"<ahora>{ahora()}</ahora>\n{texto}"},
            }
            self._proceso.stdin.write(json.dumps(mensaje).encode() + b"\n")
            await self._proceso.stdin.drain()
            while True:
                linea = await self._proceso.stdout.readline()
                if not linea:  # el proceso ha muerto: la próxima vez se arranca otro
                    yield "Perdona, se me ha cortado la conexión con Claude."
                    return
                evento = json.loads(linea)
                if evento.get("type") == "stream_event":
                    delta = evento["event"].get("delta", {})
                    if delta.get("type") == "text_delta":
                        yield delta["text"]
                elif evento.get("type") == "result":
                    if evento.get("is_error"):
                        log.warning("error de Claude: %s", evento.get("result"))
                        yield "Perdona, no he podido responder."
                    return
