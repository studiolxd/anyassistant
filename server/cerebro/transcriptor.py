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
    def __init__(self, stt, despertador, altavoz, enviar, grabar=None):
        self.enviar = enviar
        self.despertador = despertador
        self.oido = Oido(
            stt,
            al_estado=self._estado,
            al_oir=lambda texto, tiempos: enviar(
                {"tipo": "texto", "texto": texto, "tiempos": tiempos}
            ),
            despertador=despertador,
            al_despertar=lambda: altavoz.reproducir(pitido()),
            grabar=grabar,
        )

    def _estado(self, estado: str):
        mensaje = {"tipo": "estado", "estado": estado}
        if self.despertador:
            mensaje["frase"] = self.despertador.frase
        self.enviar(mensaje)

    def al_conectar(self):
        self._estado(self.oido.en_espera)

    def oir(self, pcm):
        self.oido.oir(pcm)
