"""Oído: palabra de activación, Silero VAD y transcripción con plugins.

Recibe PCM de 48 kHz en trozos de 20 ms y lo baja a 16 kHz.

- Con despertador: dormido, solo escucha la palabra. Al oírla se despierta y
  espera una frase (hasta ESPERA segundos); tras ella vuelve a dormirse.
- Sin despertador: siempre despierto, transcribe todo lo que sea voz.

Las frases se delimitan con el VAD en ventanas de 512 muestras (32 ms) y se
transcriben en un hilo aparte; el resultado llega a al_oir(texto, tiempos).
"""

import asyncio
import logging
import time
import wave
from concurrent.futures import ThreadPoolExecutor

import numpy as np
from scipy.signal import resample_poly

from stt import TASA

log = logging.getLogger("oido")

VENTANA = 512  # muestras a 16 kHz que pide Silero
UMBRAL_ON = 0.5  # probabilidad de voz para empezar
UMBRAL_OFF = 0.35  # por debajo de esto cuenta como silencio
SILENCIO = 0.6  # segundos de silencio que cierran la frase
MINIMO = 0.2  # segundos de voz mínimos para transcribir (un "hola" ronda 0,3)
MAXIMO = 15  # segundos máximos de una frase
PREVIO = 0.3  # audio que se guarda antes de detectar voz (no comerse el inicio)
ESPERA = 5  # segundos despierto esperando a que empieces a hablar

# Lo que Whisper suele inventarse con ruido o silencio en español.
FANTASMAS = (
    "amara.org",
    "subtítulos",
    "gracias por ver",
    "suscríbete",
    "¡gracias!",
)

_hilo = ThreadPoolExecutor(max_workers=1, thread_name_prefix="stt")


def cargar_vad():
    import torch
    from silero_vad import load_silero_vad

    # Un hilo basta para ventanas de 32 ms; con todos los núcleos compite con
    # el bucle de WebRTC y, con el Mac ocupado, Chrome da la conexión por perdida.
    torch.set_num_threads(1)
    return load_silero_vad()


class Oido:
    def __init__(self, stt, al_estado, al_oir, despertador=None, al_despertar=None, grabar=None):
        import torch

        self._torch = torch
        self.stt = stt
        self.despertador = despertador
        self.al_estado = al_estado
        self.al_oir = al_oir
        self.al_despertar = al_despertar or (lambda: None)
        self.vad = cargar_vad()
        self.pendiente = np.zeros(0, dtype=np.float32)
        self.previo = []
        self.frase = []
        self.hablando = False
        self.silencio = 0.0
        self.voz = 0.0  # segundos con voz dentro de la frase
        self.despierto = despertador is None
        self.despierto_desde = 0.0
        self.sordo = False  # el cerebro lo activa mientras el altavoz habla
        self.grabacion = None  # WAV con todo lo que llega, para depurar
        if grabar:
            # Un archivo por sesión: al reconectar no se pisa lo grabado.
            grabar = grabar.removesuffix(".wav") + time.strftime("-%H%M%S.wav")
            self.grabacion = wave.open(grabar, "wb")
            self.grabacion.setnchannels(1)
            self.grabacion.setsampwidth(2)
            self.grabacion.setframerate(TASA)
            log.info("grabando lo que llega en %s", grabar)

    @property
    def en_espera(self) -> str:
        if self.despertador is None:
            return "escuchando"
        return "despierto" if self.despierto else "dormido"

    def oir(self, pcm48: np.ndarray):
        audio = resample_poly(pcm48.astype(np.float32) / 32768, 1, 3).astype(np.float32)
        if self.grabacion:
            self.grabacion.writeframes((np.clip(audio, -1, 1) * 32767).astype(np.int16).tobytes())
        if self.despertador:
            # Siempre se le pasa el audio, aunque esté despierto: su historial
            # tiene que avanzar o al dormirse volvería a oír la palabra vieja.
            oida = self.despertador.escuchar(audio) and not self.sordo
            if not self.despierto:
                if oida:
                    frase = getattr(self.despertador, "frase_oida", None)
                    if frase is not None:
                        # "Hey Jarvis, ¿cómo van las cuentas?" del tirón.
                        self.despertador.frase_oida = None
                        asyncio.ensure_future(self._transcribir(frase, time.time()))
                    else:
                        self._despertar()
                return
        self.pendiente = np.concatenate([self.pendiente, audio])
        while len(self.pendiente) >= VENTANA:
            ventana, self.pendiente = self.pendiente[:VENTANA], self.pendiente[VENTANA:]
            self._ventana(ventana)

    def _despertar(self):
        log.info("despierto (%s)", self.despertador.frase)
        self._reiniciar()
        self.despierto = True
        self.despierto_desde = time.time()
        self.al_estado("despierto")
        self.al_despertar()

    def _dormir(self):
        self._reiniciar()
        self.despierto = self.despertador is None

    def _ventana(self, ventana: np.ndarray):
        prob = self.vad(self._torch.from_numpy(ventana), TASA).item()
        if self.sordo:
            self._reiniciar()
            return

        if not self.hablando:
            if self.despertador and time.time() - self.despierto_desde > ESPERA:
                log.info("no has dicho nada: vuelve a dormir")
                self._dormir()
                self.al_estado(self.en_espera)
                return
            self.previo.append(ventana)
            self.previo = self.previo[-int(PREVIO * TASA / VENTANA):]
            if prob >= UMBRAL_ON:
                self.hablando = True
                self.frase = list(self.previo)
                self.silencio = 0.0
                self.voz = VENTANA / TASA
                self.al_estado("oyendo")
            return

        self.frase.append(ventana)
        if prob < UMBRAL_OFF:
            self.silencio += VENTANA / TASA
        else:
            self.silencio = 0.0
            self.voz += VENTANA / TASA
        duracion = len(self.frase) * VENTANA / TASA
        if self.silencio >= SILENCIO or duracion >= MAXIMO:
            audio = np.concatenate(self.frase)
            voz = self.voz
            self._dormir()
            if voz < MINIMO:
                log.info("descartado: muy corto (%.2f s de voz)", voz)
                self.al_estado(self.en_espera)
                return
            asyncio.ensure_future(self._transcribir(audio, time.time()))

    def _reiniciar(self):
        self.hablando = False
        self.frase = []
        self.previo = []
        self.pendiente = np.zeros(0, dtype=np.float32)
        self.silencio = 0.0
        self.voz = 0.0
        self.vad.reset_states()

    async def _transcribir(self, audio: np.ndarray, fin_frase: float):
        self.al_estado("transcribiendo")
        inicio = time.time()
        texto = await asyncio.get_running_loop().run_in_executor(
            _hilo, self.stt.transcribir, audio
        )
        tiempos = {
            "audio_s": round(len(audio) / TASA, 2),
            "stt_ms": round((time.time() - inicio) * 1000),
        }
        if texto and hasattr(self.despertador, "quitar"):
            texto = self.despertador.quitar(texto)
            if not texto:  # solo dijo la palabra: ahora sí, a esperar la frase
                self._despertar()
                return
        if not texto or any(f in texto.lower() for f in FANTASMAS):
            log.info("descartado: %r %s", texto, tiempos)
            self.al_estado(self.en_espera)
            return
        log.info("«%s» %s", texto, tiempos)
        self.al_oir(texto, tiempos)
        self.al_estado(self.en_espera)
