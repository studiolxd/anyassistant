"""Fase 3: escucha, transcribe, responde con un plugin de LLM y lo dice en voz alta.

Cada «Hey Jarvis» empieza una conversación nueva en el LLM, que la recuerda
hasta que se duerme. La respuesta llega a la pantalla a trozos, según se
genera (mensajes "texto" con el mismo id y parcial=True hasta el último), y
en cuanto se completa una frase se sintetiza y suena mientras llega la
siguiente. Mientras habla no escucha; tocar la pantalla lo calla.
"""

import asyncio
import json
import logging
import re
import time
from pathlib import Path

from audio import normalizar
from cerebro.transcriptor import Transcriptor
from texto import normalizar as palabras

log = logging.getLogger("asistente")

# Segundos sordo tras hablar (--eco): lo que tarda su voz en ir a la tablet,
# sonar y volver por el micro, más el eco de la sala. Con 0,6 s en la tablet se
# colaba la última palabra («…¿necesitas algo más?» → «¿Algo más?»).
GUARDA = 1.2
ECO_MAXIMO = 5  # palabras: un eco es un trozo corto de lo que acaba de decir
# Un eco empieza nada más acabar de hablar (tras la guarda); una respuesta tuya
# que repite sus palabras («¿Borro solo los dos promocionales…?» → «Solo los dos
# promocionales») suele empezar más tarde: solo cuenta lo que empieza en este margen.
ECO_RECIENTE = 2.5

# Confirmación de acciones que escriben: bin/jarvis-confirmar apunta la pendiente;
# si el usuario dice «sí», aquí se autoriza esa misma acción durante un minuto.
CONFIRMAR = Path(__file__).resolve().parents[2] / ".build" / "confirmar"
SI = {"si", "vale", "adelante", "hazlo", "confirmo", "claro", "correcto", "dale", "ok", "okay",
      "venga", "perfecto", "exacto", "afirmativo", "confirmado", "por", "favor"}
NO = {"no", "espera", "cancela", "cancelar", "para", "nada", "tampoco", "mejor"}


def es_si(texto: str) -> bool:
    """«Sí», «Vale, hazlo», «Sí, por favor»… pero no «No, espera» ni frases largas."""
    oidas = palabras(texto)
    return 0 < len(oidas) <= 6 and "no" not in oidas and not (set(oidas) & NO) and bool(
        set(oidas) & (SI - {"por", "favor"})
    )
FIN_DE_FRASE = re.compile(r"(?<=[.!?…;:])\s+|\n+")


def crear(stt, llm, tts=None, despertador=None, oido=None, guarda=GUARDA):
    """Devuelve la fábrica cerebro(altavoz, enviar) que espera Sesion."""

    def cerebro(altavoz, enviar):
        return Asistente(
            stt, despertador() if despertador else None, llm, tts, altavoz, enviar, oido, guarda
        )

    return cerebro


def partir(texto: str) -> tuple[list[str], str]:
    """Frases completas y lo que queda a medias: «Hola. Qué ta» → (["Hola."], "Qué ta")."""
    trozos = FIN_DE_FRASE.split(texto)
    return [t.strip() for t in trozos[:-1] if t.strip()], trozos[-1]


class Asistente(Transcriptor):
    def __init__(self, stt, despertador, llm, tts, altavoz, enviar, oido=None, guarda=GUARDA):
        super().__init__(stt, despertador, altavoz, enviar, oido, sordo=self._sordo)
        self.guarda = guarda
        self.dicho = []  # palabras de lo último que ha dicho, para reconocer su eco
        self.llm = llm
        self.tts = tts
        self.turno = asyncio.Lock()  # una respuesta cada vez, en orden
        self.numero = 0
        self.cortada = 0  # número de la respuesta que se mandó callar
        self.frases = asyncio.Queue()  # (número, frase); frase None = fin de respuesta
        if tts:
            asyncio.ensure_future(self._boca())

    def _sordo(self) -> bool:
        return self.altavoz.hablando or time.time() - self.altavoz.ultimo_sonido < self.guarda

    def _es_eco(self, texto: str, tiempos: dict) -> bool:
        """Un trozo corto de lo último que ha dicho: su propia voz colándose por el micro."""
        # Cuándo empezó la frase: ahora, menos lo que tardó el STT y lo que dura.
        empezo = time.time() - tiempos.get("stt_ms", 0) / 1000 - tiempos.get("audio_s", 0)
        if empezo - self.altavoz.ultimo_sonido > ECO_RECIENTE:
            return False
        oidas = palabras(texto)
        dichas = " ".join(self.dicho)
        return 0 < len(oidas) <= ECO_MAXIMO and f" {' '.join(oidas)} " in f" {dichas} "

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
        if self._es_eco(texto, tiempos):
            log.info("eco descartado: «%s»", texto)
            return
        self._confirmar(texto)
        super()._oido(texto, tiempos)
        asyncio.ensure_future(self._responder(texto))

    def _confirmar(self, texto: str):
        """Si hay una acción esperando el «sí» del usuario, la autoriza o la cancela."""
        pendiente_json = CONFIRMAR / "pendiente.json"
        try:
            pendiente = json.loads(pendiente_json.read_text())
        except (OSError, ValueError):
            return
        pendiente_json.unlink(missing_ok=True)
        if time.time() - pendiente.get("cuando", 0) > 120:
            return
        if es_si(texto):
            (CONFIRMAR / "confirmada.json").write_text(
                json.dumps({"firma": pendiente["firma"], "hasta": time.time() + 60})
            )
            log.info("confirmado: %s", pendiente.get("accion"))
        else:
            log.info("no confirmado («%s»): %s", texto, pendiente.get("accion"))

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
            self.dicho = palabras(respuesta)
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
