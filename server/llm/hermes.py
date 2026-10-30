"""Hermes Agent como LLM, por su API compatible con OpenAI (`hermes gateway`).

Hermes usa sus propias herramientas, memoria y credenciales: lo que ya tenga
configurado no hay que darlo otra vez. permisos.json no le aplica; lo que sí se
mantiene es la confirmación por voz: cuando Hermes pide aprobar una acción
(evento SSE `approval.request`), Jarvis te pregunta y responde a Hermes con
`once` si dices «sí» o `deny` si no (POST /v1/runs/{id}/approval).

La clave se lee de API_SERVER_KEY en ~/.hermes/.env (o HERMES_API_KEY), y la
dirección de HERMES_API_URL (por defecto http://127.0.0.1:8642).
Cada conversación es una sesión de Hermes (cabecera X-Hermes-Session-Id).
"""

import asyncio
import json
import logging
import os
import time
import uuid
from pathlib import Path

from llm import INSTRUCCIONES, LLM, registrar

log = logging.getLogger("llm")

URL = os.environ.get("HERMES_API_URL", "http://127.0.0.1:8642")
ENV = Path.home() / ".hermes" / ".env"
# Mismos archivos que la confirmación de Claude (bin/jarvis-confirmar, cerebro/asistente.py).
CONFIRMAR = Path(__file__).resolve().parents[2] / ".build" / "confirmar"
ESPERA = "Un momento, lo miro. "
PLAZO = 120  # segundos para contestar a una aprobación; luego se deniega


def clave() -> str:
    if os.environ.get("HERMES_API_KEY"):
        return os.environ["HERMES_API_KEY"]
    try:
        for linea in ENV.read_text().splitlines():
            if linea.startswith("API_SERVER_KEY="):
                return linea.split("=", 1)[1].strip().strip('"')
    except OSError:
        pass
    raise RuntimeError(f"Falta API_SERVER_KEY en {ENV}: activa la API de Hermes")


@registrar("hermes")
class Hermes(LLM):
    def __init__(self, modelo=None, mcp=None):
        super().__init__(modelo or "hermes-agent", mcp)
        self._clave = clave()
        self._http = None
        self._sesion = None
        self._turno = asyncio.Lock()

    async def _cliente(self):
        import aiohttp

        if self._http is None or self._http.closed:
            self._http = aiohttp.ClientSession(
                base_url=URL, headers={"Authorization": f"Bearer {self._clave}"},
                timeout=aiohttp.ClientTimeout(total=None, sock_connect=5),
            )
        return self._http

    async def nueva(self):
        self._sesion = f"jarvis-{uuid.uuid4().hex[:12]}"

    async def cerrar(self):
        if self._http and not self._http.closed:
            await self._http.close()

    async def responder(self, texto: str):
        import aiohttp

        async with self._turno:
            if not self._sesion:
                await self.nueva()
            http = await self._cliente()
            cuerpo = {
                "model": self.modelo, "stream": True,
                "messages": [{"role": "system", "content": INSTRUCCIONES},
                             {"role": "user", "content": texto}],
            }
            dicho = False
            try:
                async with http.post("/v1/chat/completions", json=cuerpo,
                                     headers={"X-Hermes-Session-Id": self._sesion}) as r:
                    if r.status != 200:
                        log.warning("Hermes respondió %s: %s", r.status, (await r.text())[:300])
                        yield "Perdona, Hermes no ha podido responder."
                        return
                    evento = None
                    async for linea in r.content:
                        linea = linea.decode().strip()
                        if linea.startswith("event:"):
                            evento = linea[6:].strip()
                            continue
                        if not linea.startswith("data:"):
                            evento = None if not linea else evento
                            continue
                        datos = linea[5:].strip()
                        if datos == "[DONE]":
                            return
                        datos = json.loads(datos)
                        if evento == "approval.request":
                            pregunta = self._aprobacion(datos)
                            dicho = True
                            yield pregunta
                        elif evento == "hermes.tool.progress":
                            log.info("herramienta de Hermes: %s", datos.get("tool") or datos.get("name"))
                            if not dicho:
                                dicho = True
                                yield ESPERA
                        elif evento is None:
                            delta = (datos.get("choices") or [{}])[0].get("delta", {}).get("content")
                            if delta:
                                dicho = True
                                yield delta
                        evento = None
            except aiohttp.ClientConnectorError:
                yield "No puedo hablar con Hermes: ¿está en marcha su gateway?"

    def _aprobacion(self, datos: dict) -> str:
        """Apunta la aprobación como pendiente, espera tu «sí» en segundo plano y devuelve la pregunta."""
        run_id = datos.get("run_id", "")
        accion = datos.get("description") or datos.get("reason") or datos.get("command") or "una acción"
        log.info("Hermes pide aprobación (%s): %s", run_id, accion)
        CONFIRMAR.mkdir(parents=True, exist_ok=True)
        # «consumir»: el «sí» o el «no» es para Hermes, no un mensaje nuevo para él.
        (CONFIRMAR / "pendiente.json").write_text(json.dumps(
            {"firma": run_id, "accion": accion, "cuando": time.time(), "consumir": True}, ensure_ascii=False))
        asyncio.ensure_future(self._esperar_respuesta(run_id))
        return f" Hermes quiere hacer esto: {accion}. ¿Lo hago?"

    async def _esperar_respuesta(self, run_id: str):
        pendiente, confirmada = CONFIRMAR / "pendiente.json", CONFIRMAR / "confirmada.json"
        limite = time.time() + PLAZO
        eleccion = "deny"
        while time.time() < limite:
            await asyncio.sleep(0.2)
            try:
                if json.loads(confirmada.read_text()).get("firma") == run_id:
                    confirmada.unlink(missing_ok=True)
                    eleccion = "once"
                    break
            except (OSError, ValueError):
                pass
            if not pendiente.exists():
                break  # respondió algo que no era «sí»
        pendiente.unlink(missing_ok=True)
        log.info("aprobación de Hermes (%s): %s", run_id, eleccion)
        http = await self._cliente()
        async with http.post(f"/v1/runs/{run_id}/approval", json={"choice": eleccion}) as r:
            if r.status != 200:
                log.warning("Hermes no aceptó la aprobación: %s %s", r.status, (await r.text())[:200])
