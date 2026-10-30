"""Fase 3: escucha, transcribe y responde con un plugin de LLM.

Cada «Hey Jarvis» empieza una conversación nueva en el LLM, que la recuerda
hasta que se duerme. La respuesta llega a la pantalla a trozos, según se
genera (mensajes "texto" con el mismo id y parcial=True hasta el último).
"""

import asyncio
import logging
import time

from cerebro.transcriptor import Transcriptor

log = logging.getLogger("asistente")


def crear(stt, llm, despertador=None, grabar=None):
    """Devuelve la fábrica cerebro(altavoz, enviar) que espera Sesion."""

    def cerebro(altavoz, enviar):
        return Asistente(stt, despertador() if despertador else None, llm, altavoz, enviar, grabar)

    return cerebro


class Asistente(Transcriptor):
    def __init__(self, stt, despertador, llm, altavoz, enviar, grabar=None):
        super().__init__(stt, despertador, altavoz, enviar, grabar)
        self.llm = llm
        self.turno = asyncio.Lock()  # una respuesta cada vez, en orden
        self.numero = 0

    def al_conectar(self):
        super().al_conectar()
        asyncio.ensure_future(self.llm.nueva())

    def _despierto(self):
        super()._despierto()
        asyncio.ensure_future(self.llm.nueva())

    def _oido(self, texto: str, tiempos: dict):
        super()._oido(texto, tiempos)
        asyncio.ensure_future(self._responder(texto))

    async def _responder(self, texto: str):
        async with self.turno:
            self.numero += 1
            mensaje = {"tipo": "texto", "autor": "asistente", "id": self.numero}
            self._estado("pensando")
            inicio = time.time()
            primera = None
            respuesta = ""
            async for trozo in self.llm.responder(texto):
                primera = primera or time.time() - inicio
                respuesta += trozo
                self.enviar({**mensaje, "texto": respuesta, "parcial": True})
            tiempos = {
                "llm_primera_ms": round((primera or 0) * 1000),
                "llm_ms": round((time.time() - inicio) * 1000),
            }
            self.enviar({**mensaje, "texto": respuesta, "parcial": False, "tiempos": tiempos})
            log.info("«%s» %s", respuesta, tiempos)
            self._estado(self.oido.en_espera)
