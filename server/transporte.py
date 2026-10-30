"""Transporte: una sesión WebRTC con el móvil.

Recibe micro y cámara, envía el Altavoz de vuelta y mantiene un DataChannel
"control" para mensajes JSON. No sabe nada del cerebro: se le pasa una
fábrica cerebro(altavoz, enviar) que devuelve algo con oir(pcm).
"""

import asyncio
import io
import json
import logging

from aiortc import RTCConfiguration, RTCPeerConnection, RTCSessionDescription

from audio import Altavoz, a_mono

log = logging.getLogger("transporte")


class Sesion:
    def __init__(self, id_sesion: str, cerebro):
        self.id = id_sesion
        # Sin STUN: en la red local sobra, y aiortc por defecto consulta uno de
        # Google y tarda ~5 s en responder a cada conexión.
        self.pc = RTCPeerConnection(RTCConfiguration(iceServers=[]))
        self.canal = None
        self.altavoz = Altavoz()
        self.cerebro = cerebro(self.altavoz, self.enviar)
        self.ultimo_frame = None
        self.frames = 0
        self._tareas = []

        @self.pc.on("datachannel")
        def on_datachannel(canal):
            self.canal = canal
            if hasattr(self.cerebro, "al_conectar"):
                self.cerebro.al_conectar()

            @canal.on("message")
            def on_message(mensaje):
                self._mensaje(json.loads(mensaje))

        @self.pc.on("track")
        def on_track(track):
            log.info("[%s] pista recibida: %s", self.id, track.kind)
            if track.kind == "audio":
                self.pc.addTrack(self.altavoz)
                self._tareas.append(asyncio.ensure_future(self._leer_audio(track)))
            elif track.kind == "video":
                self._tareas.append(asyncio.ensure_future(self._leer_video(track)))

        @self.pc.on("connectionstatechange")
        async def on_estado():
            log.info("[%s] conexión: %s", self.id, self.pc.connectionState)
            if self.pc.connectionState in ("failed", "closed"):
                await self.cerrar()

    async def responder(self, sdp: str, tipo: str) -> RTCSessionDescription:
        await self.pc.setRemoteDescription(RTCSessionDescription(sdp=sdp, type=tipo))
        await self.pc.setLocalDescription(await self.pc.createAnswer())
        return self.pc.localDescription

    def enviar(self, datos: dict):
        if self.canal and self.canal.readyState == "open":
            self.canal.send(json.dumps(datos))

    def _mensaje(self, datos: dict):
        if datos.get("tipo") == "ping":
            self.enviar({"tipo": "pong", "t": datos["t"]})

    async def _leer_audio(self, track):
        try:
            while True:
                self.cerebro.oir(a_mono(await track.recv()))
        except Exception:
            log.info("[%s] fin del audio", self.id)

    async def _leer_video(self, track):
        try:
            while True:
                self.ultimo_frame = await track.recv()
                self.frames += 1
        except Exception:
            pass

    def jpeg(self) -> bytes | None:
        if self.ultimo_frame is None:
            return None
        buf = io.BytesIO()
        self.ultimo_frame.to_image().save(buf, format="JPEG", quality=75)
        return buf.getvalue()

    async def cerrar(self):
        for tarea in self._tareas:
            tarea.cancel()
        await self.pc.close()
