"""Plugins de LLM (texto → respuesta en streaming).

Un plugin es un módulo de este paquete con una clase registrada así:

    @registrar("nombre")
    class MiLLM(LLM):
        async def nueva(self): ...              # empieza conversación (olvida la anterior)
        async def responder(self, texto):       # async generator de trozos de texto
            yield "Hola"
"""

import time
from collections.abc import AsyncIterator

from plugins import Registro

_registro = Registro(__name__, __path__, "LLM")
registrar = _registro.registrar
crear = _registro.crear
disponibles = _registro.disponibles

DIAS = ("lunes", "martes", "miércoles", "jueves", "viernes", "sábado", "domingo")
MESES = ("enero", "febrero", "marzo", "abril", "mayo", "junio", "julio", "agosto",
         "septiembre", "octubre", "noviembre", "diciembre")

INSTRUCCIONES = """Eres Jarvis, un asistente de voz que habla español de España.
Lo que te llega es lo que el usuario ha dicho en voz alta, transcrito
automáticamente: puede tener errores; interprétalo con sentido común.
Tu respuesta se leerá en voz alta: sé breve (una a tres frases), natural y
directo. Nada de listas, markdown, emojis ni símbolos. Si no sabes algo, dilo.
Si te preguntan la fecha o la hora, consúltalas con la herramienta fechaHora."""


def ahora() -> str:
    """«viernes 30 de octubre de 2026, las 8 y 42 de la noche».

    En forma hablada: con «20:42» el modelo pequeño se lía al pasarlo a voz
    («las dos veinte y cuarenta dos»). Los plugins se la dan al modelo como
    herramienta, no en el prompt, o la repite en todas las respuestas.
    """
    t = time.localtime()
    hora = t.tm_hour % 12 or 12
    parte = "de la mañana" if 6 <= t.tm_hour < 12 else "de la tarde" if 12 <= t.tm_hour < 20 else (
        "de la noche" if t.tm_hour >= 20 else "de la madrugada")
    minutos = "en punto" if t.tm_min == 0 else f"y {t.tm_min}"
    articulo = "la" if hora == 1 else "las"
    fecha = f"{DIAS[t.tm_wday]} {t.tm_mday} de {MESES[t.tm_mon - 1]} de {t.tm_year}"
    return f"{fecha}, {articulo} {hora} {minutos} {parte}"


class LLM:
    nombre = "?"

    def __init__(self, modelo: str | None = None):
        self.modelo = modelo

    async def nueva(self):
        raise NotImplementedError

    def responder(self, texto: str) -> AsyncIterator[str]:
        raise NotImplementedError
