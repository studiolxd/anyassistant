"""El modelo de Apple que viene con macOS (Foundation Models, ~3B, en local).

Habla con apple_puente.swift, que se compila la primera vez en .build/.
Requiere macOS 26+ con Apple Intelligence activado.
"""

import asyncio
import json
import logging
import subprocess
from pathlib import Path

from llm import INSTRUCCIONES, LLM, ahora, registrar
from swift import compilar

log = logging.getLogger("llm")

# Si se le da la hora en el prompt la repite en cada respuesta: va como herramienta.
INSTRUCCIONES_APPLE = (
    INSTRUCCIONES + "\nSi te preguntan la fecha o la hora, consúltalas con la herramienta fechaHora."
)

@registrar("apple")
class Apple(LLM):
    def __init__(self, modelo=None):
        super().__init__(modelo or "SystemLanguageModel.default")
        self._binario = compilar(Path(__file__).with_name("apple_puente.swift"), "fm-puente")
        self._proceso = None
        self._turno = asyncio.Lock()  # el puente atiende una orden cada vez

    async def _arrancar(self):
        if self._proceso and self._proceso.returncode is None:
            return
        self._proceso = await asyncio.create_subprocess_exec(
            str(self._binario), stdin=subprocess.PIPE, stdout=subprocess.PIPE
        )
        listo = await self._leer()
        if "error" in listo:
            raise RuntimeError(f"modelo de Apple: {listo['error']}")

    async def _leer(self) -> dict:
        return json.loads(await self._proceso.stdout.readline())

    async def _enviar(self, orden: dict):
        self._proceso.stdin.write(json.dumps(orden).encode() + b"\n")
        await self._proceso.stdin.drain()

    async def cerrar(self):
        if self._proceso and self._proceso.returncode is None:
            self._proceso.kill()
            await self._proceso.wait()

    async def nueva(self):
        async with self._turno:
            await self._arrancar()
            await self._enviar({"tipo": "nueva", "instrucciones": INSTRUCCIONES_APPLE})
            await self._leer()

    async def responder(self, texto: str):
        async with self._turno:
            await self._arrancar()
            await self._enviar({"tipo": "preguntar", "texto": texto, "ahora": ahora()})
            while True:
                mensaje = await self._leer()
                if "delta" in mensaje:
                    yield mensaje["delta"]
                elif "error" in mensaje:
                    log.warning("error del modelo: %s", mensaje["error"])
                    yield mensaje.get("mensaje", "Perdona, no he podido responder.")
                    return
                else:
                    return
