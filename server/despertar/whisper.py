"""Palabra de activación con un Whisper pequeño: vale para cualquier palabra.

Silero VAD corta las frases; cada una se transcribe con whisper-base (~140 ms
en un M4) y se busca la palabra entre las primeras, comparando por cómo suena
(«Yarvis», «Harvis», «G&J Arbis»…). Si la frase sigue tras la palabra
("Hey Jarvis, ¿cómo van las cuentas?"), la deja en frase_oida para
transcribirla entera.
"""

import logging
import re
import unicodedata
from difflib import SequenceMatcher

import numpy as np

from despertar import TASA, Despertador, registrar

log = logging.getLogger("despertar")

VENTANA = 512
UMBRAL_ON = 0.5
UMBRAL_OFF = 0.35
SILENCIO = 0.5  # más corto que el del oído: la palabra suele ir sola
MAXIMO = 15
PREVIO = 0.3
PRIMERAS = 3  # la palabra tiene que estar al principio ("…le dijo a Jarvis…" no vale)
PARECIDO = 0.85  # «ya veis» da 0,83; las buenas, 1,00


def normalizar(texto: str) -> list[str]:
    sin_tildes = unicodedata.normalize("NFKD", texto.lower())
    sin_tildes = "".join(c for c in sin_tildes if not unicodedata.combining(c))
    return re.findall(r"[a-zñ]+", sin_tildes)


def fonetica(palabra: str) -> str:
    """Cómo suena, más o menos: «Jarvis», «Yarvis», «Harvis» → «yarbis»/«arbis»."""
    for a, b in (("ll", "y"), ("j", "y"), ("g", "y"), ("v", "b"), ("h", ""), ("z", "s")):
        palabra = palabra.replace(a, b)
    return palabra


def parecido(candidata: str, clave: str) -> float:
    """Parecido de la clave con la candidata o con un trozo suyo («gellarby»)."""
    mejor = SequenceMatcher(None, candidata, clave).ratio()
    for i in range(max(len(candidata) - len(clave) + 1, 0)):
        trozo = candidata[i : i + len(clave)]
        mejor = max(mejor, SequenceMatcher(None, trozo, clave).ratio())
    return mejor


@registrar("whisper")
class WhisperDespertador(Despertador):
    def __init__(self, palabra=None, umbral=PARECIDO, modelo="mlx-community/whisper-base-mlx"):
        super().__init__(palabra or "jarvis", umbral)
        import torch

        from cerebro.oido import cargar_vad
        from stt.mlx_whisper import transcribir_mlx

        self._torch = torch
        self._transcribir = transcribir_mlx
        self.modelo = modelo
        self.claves = normalizar(self.palabra)
        self.frase = "Hey Jarvis" if self.claves == ["jarvis"] else self.palabra.capitalize()
        # Sin pista, whisper-base escribe «Geri Yarvis», «gellarby»…; con la
        # frase exacta como pista se la salta (cree que ya estaba dicha).
        self.pista = f"El asistente se llama {self.palabra.title()}."
        self.vad = cargar_vad()
        self.frase_oida = None  # audio completo si la frase sigue tras la palabra
        self._reiniciar()
        self._transcribir(np.zeros(TASA // 2, dtype=np.float32), self.modelo, "es")

    def _reiniciar(self):
        self.pendiente = np.zeros(0, dtype=np.float32)
        self.previo = []
        self.trozos = []
        self.hablando = False
        self.silencio = 0.0
        self.vad.reset_states()

    def reiniciar(self):
        self._reiniciar()

    def escuchar(self, audio: np.ndarray) -> bool:
        self.pendiente = np.concatenate([self.pendiente, audio])
        oida = False
        while len(self.pendiente) >= VENTANA:
            ventana, self.pendiente = self.pendiente[:VENTANA], self.pendiente[VENTANA:]
            oida = self._ventana(ventana) or oida
        return oida

    def _ventana(self, ventana: np.ndarray) -> bool:
        prob = self.vad(self._torch.from_numpy(ventana), TASA).item()
        if not self.hablando:
            self.previo = (self.previo + [ventana])[-int(PREVIO * TASA / VENTANA):]
            if prob >= UMBRAL_ON:
                self.hablando = True
                self.trozos = list(self.previo)
                self.silencio = 0.0
            return False

        self.trozos.append(ventana)
        self.silencio = self.silencio + VENTANA / TASA if prob < UMBRAL_OFF else 0.0
        if self.silencio < SILENCIO and len(self.trozos) * VENTANA / TASA < MAXIMO:
            return False

        audio = np.concatenate(self.trozos)
        self.hablando = False
        self.trozos = []
        self.previo = []
        return self._buscar(audio)

    def _posicion(self, palabras: list[str]) -> tuple[int, int] | None:
        """(índice, nº de palabras) de la palabra de activación entre las primeras.

        Prueba también juntando una palabra más: Whisper a veces la parte
        («G&J Arbis» → «j» + «arbis»).
        """
        clave = fonetica("".join(self.claves))
        n = len(self.claves)
        for i in range(min(PRIMERAS, len(palabras))):
            for tramo in (n, n + 1):
                if i + tramo > len(palabras):
                    break
                candidata = fonetica("".join(palabras[i : i + tramo]))
                if parecido(candidata, clave) >= self.umbral:
                    return i, tramo
        return None

    def quitar(self, texto: str) -> str:
        """«Hey Jarvis, ¿cómo van las cuentas?» → «¿cómo van las cuentas?»"""
        fichas = list(re.finditer(r"\w+", texto))
        posicion = self._posicion(["".join(normalizar(f.group())) for f in fichas])
        if posicion is None:
            return texto
        i, tramo = posicion
        return texto[fichas[i + tramo - 1].end() :].lstrip(" ,.!:;-")

    def _buscar(self, audio: np.ndarray) -> bool:
        texto = self._transcribir(audio, self.modelo, "es", self.pista)
        palabras = normalizar(texto)
        posicion = self._posicion(palabras)
        if posicion is None:
            if texto:
                log.info("sin palabra: «%s»", texto)
            return False
        log.info("palabra en «%s»", texto)
        i, tramo = posicion
        self.frase_oida = audio if palabras[i + tramo :] else None
        return True
