"""Fase 2: escucha y muestra lo que dices en la pantalla del móvil."""

from audio import pitido
from cerebro.oido import Oido


def crear(stt, despertador=None, grabar=None):
    """Devuelve la fábrica cerebro(altavoz, enviar) que espera Sesion.

    despertador es una función que crea un Despertador nuevo (uno por sesión,
    porque guarda estado) o None para escuchar sin palabra de activación.
    """

    def cerebro(altavoz, enviar):
        return Transcriptor(stt, despertador() if despertador else None, altavoz, enviar, grabar)

    return cerebro


class Transcriptor:
    def __init__(self, stt, despertador, altavoz, enviar, grabar=None, sordo=None):
        self.enviar = enviar
        self.altavoz = altavoz
        self.despertador = despertador
        self.oido = Oido(
            stt,
            al_estado=self._estado,
            al_oir=self._oido,
            despertador=despertador,
            al_despertar=self._despierto,
            al_dormir=self._dormir,
            grabar=grabar,
            sordo=sordo,
        )

    def _oido(self, texto: str, tiempos: dict):
        self.enviar({"tipo": "texto", "texto": texto, "tiempos": tiempos})

    def _despierto(self):
        self.altavoz.reproducir(pitido())

    def _dormir(self, por_orden: bool):
        self.altavoz.reproducir(pitido(bajando=True))
        if por_orden:
            self.enviar({"tipo": "texto", "texto": "Hasta la próxima", "autor": "asistente"})

    def _estado(self, estado: str):
        mensaje = {"tipo": "estado", "estado": estado}
        if self.despertador:
            mensaje["frase"] = self.despertador.frase
        self.enviar(mensaje)

    def al_conectar(self):
        self._estado(self.oido.en_espera)

    def oir(self, pcm):
        self.oido.oir(pcm)
