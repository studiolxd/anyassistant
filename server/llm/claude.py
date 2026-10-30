"""Claude a través de la CLI de Claude Code: usa tu sesión y tu suscripción, sin API key.

Una conversación es un proceso `claude -p` en modo stream-json: recibe los
mensajes por stdin y devuelve la respuesta a trozos (--include-partial-messages).
Sin las herramientas de Claude Code ni CLAUDE.md. Los MCP, solo los que permita
mcp.json (ver llm/mcp.py); sin ese archivo, ninguno y arranca en 0,2 s.
Requiere `claude` instalado y con sesión iniciada.
"""

import asyncio
import json
import logging
from pathlib import Path

from llm import INSTRUCCIONES, LLM, ahora, registrar
from llm import mcp as permisos_mcp

log = logging.getLogger("llm")

INSTRUCCIONES_CLAUDE = INSTRUCCIONES + """
Cada mensaje empieza con <ahora>…</ahora>, la fecha y hora actuales: úsalas
solo si te preguntan por ellas y no las menciones si no."""

INSTRUCCIONES_MCP = """
Tienes herramientas para consultar servicios del usuario: úsalas cuando hagan
falta y resume el resultado en una o dos frases para decirlas en voz alta."""

# Si va a usar una herramienta sin haber dicho nada, para que no haya silencio
# (pedírselo en el prompt no basta: casi nunca lo hace).
ESPERA = "Un momento, lo miro. "

RAIZ = Path(__file__).resolve().parents[2]
# Un directorio vacío como cwd: así no carga el CLAUDE.md de ningún proyecto.
VACIO = RAIZ / ".build" / "claude-vacio"
MCP_JSON = RAIZ / "mcp.json"


@registrar("claude")
class Claude(LLM):
    def __init__(self, modelo=None, mcp=None):
        super().__init__(modelo or "sonnet", mcp or str(MCP_JSON))
        VACIO.mkdir(parents=True, exist_ok=True)
        self._mcp = permisos_mcp.argumentos(Path(self.mcp), VACIO.parent / "mcp-propios.json")
        self._instrucciones = INSTRUCCIONES_CLAUDE
        if "--allowedTools" in self._mcp:
            self._instrucciones += INSTRUCCIONES_MCP
        self._proceso = None
        self._turno = asyncio.Lock()

    async def _arrancar(self):
        self._proceso = await asyncio.create_subprocess_exec(
            "claude", "-p",
            "--input-format", "stream-json",
            "--output-format", "stream-json",
            "--include-partial-messages", "--verbose",
            "--model", self.modelo,
            "--system-prompt", self._instrucciones,
            "--no-session-persistence",
            *self._mcp,
            "--tools", "",  # sin herramientas propias de Claude Code (Bash, Edit…)
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
            dicho = False
            while True:
                linea = await self._proceso.stdout.readline()
                if not linea:  # el proceso ha muerto: la próxima vez se arranca otro
                    yield "Perdona, se me ha cortado la conexión con Claude."
                    return
                evento = json.loads(linea)
                if evento.get("type") == "stream_event":
                    delta = evento["event"].get("delta", {})
                    bloque = evento["event"].get("content_block", {})
                    if delta.get("type") == "text_delta":
                        dicho = True
                        yield delta["text"]
                    elif bloque.get("type") == "tool_use":
                        log.info("herramienta: %s", bloque.get("name"))
                        if not dicho:
                            dicho = True
                            yield ESPERA
                elif evento.get("type") == "result":
                    if evento.get("is_error"):
                        log.warning("error de Claude: %s", evento.get("result"))
                        yield "Perdona, no he podido responder."
                    return
