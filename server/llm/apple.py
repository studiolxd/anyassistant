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

log = logging.getLogger("llm")

FUENTE = Path(__file__).with_name("apple_puente.swift")
BINARIO = Path(__file__).resolve().parents[2] / ".build" / "fm-puente"


def compilar():
    if BINARIO.exists() and BINARIO.stat().st_mtime >= FUENTE.stat().st_mtime:
        return
    log.info("compilando %s…", FUENTE.name)
    BINARIO.parent.mkdir(exist_ok=True)
    subprocess.run(["swiftc", "-O", str(FUENTE), "-o", str(BINARIO)], check=True)


@registrar("apple")
class Apple(LLM):
    def __init__(self, modelo=None):
        super().__init__(modelo or "SystemLanguageModel.default")
        compilar()
        self._proceso = None
        self._turno = asyncio.Lock()  # el puente atiende una orden cada vez

    async def _arrancar(self):
        if self._proceso and self._proceso.returncode is None:
            return
        self._proceso = await asyncio.create_subprocess_exec(
            str(BINARIO), stdin=subprocess.PIPE, stdout=subprocess.PIPE
        )
        listo = await self._leer()
        if "error" in listo:
            raise RuntimeError(f"modelo de Apple: {listo['error']}")

    async def _leer(self) -> dict:
        return json.loads(await self._proceso.stdout.readline())

    async def _enviar(self, orden: dict):
        self._proceso.stdin.write(json.dumps(orden).encode() + b"\n")
        await self._proceso.stdin.drain()

    async def nueva(self):
        async with self._turno:
            await self._arrancar()
            await self._enviar({"tipo": "nueva", "instrucciones": INSTRUCCIONES})
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
