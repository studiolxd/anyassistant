# Nexus voz

El Nexus 4 hace de ojos, boca y oídos; todo el procesamiento va en el Mac.
Transporte WebRTC (Opus + cancelación de eco de Chrome) por Wi-Fi.

## Fase 0 · Preparar el móvil

1. ROM con Android 7.1 y Chrome actualizado desde Play Store.
2. IP fija para el Mac (ahora `192.168.1.137`): en macOS, Wi-Fi → Detalles de la red →
   *Dirección Wi-Fi privada* en **Fija** (en *Rotativa* cambia de IP), y mejor aún una
   reserva DHCP en el router. El móvil, en la red de 5 GHz si la hay.
3. En Chrome del móvil: `chrome://flags` → *Insecure origins treated as secure* →
   `http://192.168.1.137:8080` → *Enabled* → Relaunch.
4. Ajustes → Batería → optimización: Chrome *sin optimizar*.

## Arrancar

```
uv run server/main.py                 # Fase 2: transcribe (Silero VAD + mlx-whisper)
uv run server/main.py --modo loro     # Fase 1: repite lo que oye (prueba de micro y altavoz)
```

La primera vez descarga `whisper-large-v3-turbo` (~1,6 GB).

- Móvil: `http://192.168.1.137:8080` → **Empezar** → permitir micro y cámara.
- Mac: `http://localhost:8080/monitor` para ver la cámara.

La primera vez macOS pregunta si Python puede aceptar conexiones entrantes: *Permitir*.

## Fase 1 · Loro

Graba lo que dices y lo repite al terminar; mientras repite no escucha (un eco
directo se acoplaba: la cancelación de eco de la tablet no basta). Sirve para
probar micro, altavoz y red (RTT, jitter y perdidos salen abajo en la pantalla).

## Fase 2 · Oídos

Silero VAD separa la voz del ruido; cuando terminas una frase (0,6 s de silencio)
se transcribe y sale como subtítulo en el móvil. Los tiempos van al log del Mac.

### Plugins de STT

Cada módulo de `server/stt/` es un motor. Para añadir uno:

```python
# server/stt/mi_motor.py
from stt import Transcriptor, registrar

@registrar("mi-motor")
class MiMotor(Transcriptor):
    def transcribir(self, audio):  # float32 mono 16 kHz → str
        ...
```

y se usa con `--stt mi-motor [--stt-modelo ...]`. Las dependencias pesadas,
dentro de la clase para no cargarlas si no se usa.

## Palabra de activación

Por defecto duerme hasta oír **«Hey Jarvis»** (openWakeWord, en la CPU del Mac):
pita, espera tu frase hasta 5 s, la transcribe y vuelve a dormir.

```
uv run server/main.py --palabra alexa          # otra de serie: alexa, hey_mycroft, hey_rhasspy…
uv run server/main.py --palabra ~/modelos/x.onnx   # un modelo propio de openWakeWord
uv run server/main.py --umbral 0.6             # más exigente si se despierta solo
uv run server/main.py --despertar ninguno      # sin palabra: transcribe toda la voz
```

Otros motores (Vosk, Porcupine…) son plugins en `server/despertar/`:

```python
# server/despertar/mi_motor.py
from despertar import Despertador, registrar

@registrar("mi-motor")
class MiMotor(Despertador):
    frase = "Oye Nexus"              # lo que se muestra en la pantalla
    def escuchar(self, audio):       # float32 mono 16 kHz, trozos de cualquier tamaño
        return detectado             # True en el trozo en que oye la palabra
```

y `--despertar mi-motor [--palabra …]`. `server/plugins.py` es el registro común.

## Estructura

- `server/main.py` — HTTP, señalización (`/offer`), monitor (`/video.mjpg`, `/estado`).
- `server/transporte.py` — sesión WebRTC: pistas, DataChannel `control`, último fotograma.
- `server/audio.py` — PCM mono 48 kHz; `Altavoz` es la pista de salida.
- `server/cerebro/` — `loro.py` (Fase 1), `oido.py` (VAD + STT), `transcriptor.py` (Fase 2).
- `server/stt/` — plugins de voz a texto.
- `server/despertar/` — plugins de palabra de activación.
- `server/plugins.py` — registro común de plugins.
- `web/` — la página del móvil (JS sin bundler, Chrome ≤ 119) y el monitor.

Próximas fases: boca (LLM + TTS en streaming con interrupción),
ojos (captura bajo demanda), cara, y después app nativa con libwebrtc contra el mismo servidor.
