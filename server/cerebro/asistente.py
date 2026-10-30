"""Fase 3: escucha, transcribe, responde con un plugin de LLM y lo dice en voz alta.

Cada «Hey Jarvis» empieza una conversación nueva en el LLM, que la recuerda
hasta que se duerme. La respuesta llega a la pantalla a trozos, según se
genera (mensajes "texto" con el mismo id y parcial=True hasta el último), y
en cuanto se completa una frase se sintetiza y suena mientras llega la
siguiente. Mientras habla no escucha; tocar la pantalla lo calla.
"""

import asyncio
import logging
import re
import time

from audio import normalizar
from cerebro.transcriptor import Transcriptor

log = logging.getLogger("asistente")

GUARDA = 0.6  # segundos sordo tras hablar: latencia hasta el altavoz + eco de la sala
FIN_DE_FRASE = re.compile(r"(?<=[.!?…;:])\s+|\n+")


def crear(stt, llm, tts=None, despertador=None, grabar=None):
    """Devuelve la fábrica cerebro(altavoz, enviar) que espera Sesion."""

    def cerebro(altavoz, enviar):
        return Asistente(
            stt, despertador() if despertador else None, llm, tts, altavoz, enviar, grabar
        )

    return cerebro


def partir(texto: str) -> tuple[list[str], str]:
    """Frases completas y lo que queda a medias: «Hola. Qué ta» → (["Hola."], "Qué ta")."""
    trozos = FIN_DE_FRASE.split(texto)
    return [t.strip() for t in trozos[:-1] if t.strip()], trozos[-1]


class Asistente(Transcriptor):
    def __init__(self, stt, despertador, llm, tts, altavoz, enviar, grabar=None):
        super().__init__(stt, despertador, altavoz, enviar, grabar, sordo=self._sordo)
        self.llm = llm
        self.tts = tts
        self.turno = asyncio.Lock()  # una respuesta cada vez, en orden
        self.numero = 0
        self.cortada = 0  # número de la respuesta que se mandó callar
        self.frases = asyncio.Queue()  # (número, frase); frase None = fin de respuesta
        if tts:
            asyncio.ensure_future(self._boca())

    def _sordo(self) -> bool:
        return self.altavoz.hablando or time.time() - self.altavoz.ultimo_sonido < GUARDA

    def al_conectar(self):
        super().al_conectar()
        asyncio.ensure_future(self.llm.nueva())

    def al_mensaje(self, datos: dict):
        if datos.get("tipo") == "tocar" and (self.turno.locked() or self.altavoz.hablando):
            self.callar()

    def callar(self):
        log.info("callado")
        self.cortada = self.numero
        self.altavoz.callar()
        self._estado(self.oido.en_espera)

    def _despierto(self):
        super()._despierto()
        asyncio.ensure_future(self.llm.nueva())

    def _oido(self, texto: str, tiempos: dict):
        super()._oido(texto, tiempos)
        asyncio.ensure_future(self._responder(texto))

    async def _responder(self, texto: str):
        async with self.turno:
            self.numero += 1
            numero = self.numero
            mensaje = {"tipo": "texto", "autor": "asistente", "id": numero}
            self._estado("pensando")
            inicio = time.time()
            primera = None
            respuesta = pendiente = ""
            # Aunque se corte, se lee la respuesta entera: el plugin tiene que acabarla.
            async for trozo in self.llm.responder(texto):
                if self.cortada == numero:
                    continue
                primera = primera or time.time() - inicio
                respuesta += trozo
                self.enviar({**mensaje, "texto": respuesta, "parcial": True})
                if self.tts:
                    frases, pendiente = partir(pendiente + trozo)
                    for frase in frases:
                        self.frases.put_nowait((numero, frase))
            if self.tts:
                if pendiente.strip():
                    self.frases.put_nowait((numero, pendiente.strip()))
                self.frases.put_nowait((numero, None))
            tiempos = {
                "llm_primera_ms": round((primera or 0) * 1000),
                "llm_ms": round((time.time() - inicio) * 1000),
            }
            self.enviar({**mensaje, "texto": respuesta, "parcial": False, "tiempos": tiempos})
            log.info("«%s» %s", respuesta, tiempos)
            if not self.tts and self.cortada != numero:
                self._estado(self.oido.en_espera)

    async def _boca(self):
        """Dice las frases en orden según llegan; sintetiza una mientras suena la anterior."""
        bucle = asyncio.get_running_loop()
        while True:
            numero, frase = await self.frases.get()
            if numero == self.cortada:
                continue
            if frase is None:  # fin de la respuesta: esperar a que acabe de sonar
                while self.altavoz.hablando and numero != self.cortada:
                    await asyncio.sleep(0.05)
                if numero != self.cortada:
                    self._estado(self.oido.en_espera)
                continue
            inicio = time.time()
            pcm = await bucle.run_in_executor(None, self.tts.sintetizar, frase)
            if numero == self.cortada:
                continue
            if not self.altavoz.hablando:
                self._estado("hablando")
            self.altavoz.reproducir(normalizar(pcm))
            log.info("voz «%s» (%d ms)", frase, (time.time() - inicio) * 1000)
