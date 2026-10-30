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
uv run server/main.py                    # Fase 3: asistente (Parakeet + Claude + AVSpeech)
uv run server/main.py --modo transcribir # Fase 2: solo transcribe
uv run server/main.py --modo loro        # Fase 1: repite lo que oye (prueba de micro y altavoz)
```

La primera vez descarga los modelos (Parakeet ~1,2 GB, Whisper turbo ~1,6 GB, Whisper base).

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

### Motores de transcripción

Comparados con 32 frases reales dichas a la tablet (mediana por frase, en un M4):

| `--stt` / `--stt-modelo` | Mediana | Notas |
|---|---|---|
| **`parakeet`** (por defecto) | 114 ms | Parakeet TDT v3; acierta tanto o más que turbo |
| `mlx-whisper` (turbo) | 938 ms | Rellena el audio hasta 30 s: lento con frases cortas |
| `mlx-whisper --stt-modelo mlx-community/whisper-small-mlx` | 230 ms | Más errores |
| `mlx-whisper --stt-modelo mlx-community/whisper-base-mlx` | 76 ms | Muchos errores |

Parakeet detecta el idioma solo y a veces se va al inglés («¿Qué hora es?» →
«Koda is a very good idea»); si el resultado parece inglés, esa frase se repite
con Whisper turbo en español. «Apágate» se reconoce por parecido («Apparaté»).

`--silencio` (0,6 s por defecto) es el silencio que cierra una frase: más bajo
responde antes pero puede cortarte si haces pausas; `--inactividad` (120 s), lo
que tarda en dormirse si no le hablas.

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

## Palabra de activación y modo conversación

Duerme hasta oír **«Hey Jarvis»**; entonces pita y entra en **modo conversación**:
transcribe frase a frase sin repetir la palabra, hasta que le dices **«apágate»**
(o «duérmete») o pasan **2 minutos** sin hablarle; al dormirse pita hacia abajo.
«Hey Jarvis, ¿cómo van las cuentas?» del tirón también vale: despierta y transcribe
la pregunta.

Por defecto la palabra la busca un Whisper pequeño (`whisper-base`, ~140 ms),
comparando por cómo suena («Yarvis», «Harvis»…); vale para cualquier palabra.
openWakeWord sigue como plugin, pero con acento español apenas reconoce «Hey Jarvis».

```
uv run server/main.py --palabra nexus          # cualquier palabra con el plugin whisper
uv run server/main.py --umbral 0.9             # más exigente si se despierta solo
uv run server/main.py --despertar openwakeword --palabra alexa   # alexa, hey_jarvis, hey_mycroft…
uv run server/main.py --despertar ninguno      # sin palabra: transcribe toda la voz
```

Otros motores (Vosk, Porcupine…) son plugins en `server/despertar/`:

```python
# server/despertar/mi_motor.py
from despertar import Despertador, registrar

@registrar("mi-motor")
class MiMotor(Despertador):
    frase = "Oye Nexus"              # lo que se muestra en la pantalla
    continuo = False                 # True si necesita oír también estando despierto
    def escuchar(self, audio):       # float32 mono 16 kHz, trozos de cualquier tamaño
        return detectado             # True en el trozo en que oye la palabra
```

y `--despertar mi-motor [--palabra …]`. `server/plugins.py` es el registro común.

## Fase 3 · Respuestas (LLM)

Lo que dices va al LLM y la respuesta aparece en pantalla según se genera.
Cada «Hey Jarvis» empieza una conversación nueva; la recuerda hasta que se duerme.

Hay dos plugins:

- **`claude`** (por defecto): Claude a través de la CLI `claude` de Claude Code, con
  tu sesión y tu suscripción, sin API key. Cada conversación es un proceso
  `claude -p` en modo stream-json, sin herramientas, MCP ni CLAUDE.md, para que
  arranque rápido. Sonnet por defecto; `--llm-modelo haiku` gasta menos cuota.
  Primera palabra en ~0,6 s.
- **`apple`**: el modelo que trae macOS (Foundation Models, local, sin claves;
  macOS 26+ con Apple Intelligence). Es una API solo de Swift: el plugin compila
  `server/llm/apple_puente.swift` la primera vez en `.build/` y le habla por
  stdin/stdout. La hora se la da como herramienta (`fechaHora`): en el prompt la
  repetía en cada respuesta. Más rápido (~0,5 s) pero más flojo (~3B).

```
uv run server/main.py --llm-modelo haiku   # Claude Haiku
uv run server/main.py --llm apple          # modelo de Apple, en local
```

### Herramientas: solo las del proyecto y solo lo que permitas

Con el plugin `claude`, Jarvis puede usar **servidores MCP de la carpeta del proyecto**
y **comandos del proyecto**, nunca los conectores de tu cuenta de claude.ai ni otras
órdenes de terminal. Todo se decide en **`permisos.json`** (fuera de git; ver
`permisos.ejemplo.json`):

```json
{
  "permitidos": { "holded": "todo" },
  "comandos": { "bin/gog": "todo" },
  "confirmar": true
}
```

- `permitidos`: herramientas de cada servidor de **`.mcp.json`** (`"todo"` o una
  lista); un servidor que no aparezca queda prohibido entero.
- `comandos`: programas que puede ejecutar, con su política (la lee el propio
  comando). Claude recibe la terminal de Claude Code **limitada a ellos** (lo demás se
  le deniega: probado con `ls`, `curl` y `touch`) y, en el prompt, lo que muestra
  `<comando> ayuda`.
- `confirmar` (sí por defecto): **las acciones que escriben necesitan tu «sí» por voz**.
  Un hook de Claude Code (`bin/jarvis-confirmar`) frena cualquier `bin/gog` que no sea
  de lectura y cualquier herramienta MCP que no sea `get_`/`list_`/`search_`…, y Claude
  te pregunta. Si dices «sí» (o «vale», «adelante»…; «sí, pero…» no cuenta), el servidor
  autoriza **esa misma llamada**, una vez y durante un minuto; cualquier otra respuesta
  la cancela. Claude no puede saltárselo: no puede escribir archivos ni ejecutar otra
  cosa.

Sin `permisos.json` no usa nada. Al usar una herramienta dice «Un momento, lo miro».

#### Holded (MCP)

En `.mcp.json` (ver `.mcp.ejemplo.json`); se autentica en la carpeta del proyecto:
`claude` → aprobar los servidores → `/mcp` → *Authenticate*. El solo lectura se elige
al autorizarlo en Holded. Su registro automático de clientes falla en Claude Code
(devuelve `"software_id": null`), así que se registra uno a mano y su `clientId` va en
`.mcp.json` (puerto de vuelta 8766):

```
curl -X POST https://app.holded.com/api/v2/mcp/oauth/register -H "Content-Type: application/json" \
  -d '{"client_name":"Jarvis","redirect_uris":["http://localhost:8766/callback"],
       "grant_types":["authorization_code","refresh_token"],"response_types":["code"],
       "token_endpoint_auth_method":"none"}'
```

#### Gmail, Calendar, Drive, Docs y Sheets (`bin/gog`)

Con [gog](https://gogcli.sh) (`brew install openclaw/tap/gogcli`). `bin/gog` lo
lanza siempre con el cliente `jarvis` (su propio depósito de tokens), la configuración
en `.gog/` dentro del proyecto y `--no-input`, y se niega si le intentan cambiar esas
opciones. Su política, en `permisos.json`:

- `"lectura"`: `--readonly`, `--gmail-no-send` y solo órdenes de lectura; la
  autorización solo pide permisos de lectura a Google.
- `"todo"`: puede escribir (siempre con la confirmación por voz), salvo gestionar la
  sesión de gog, copias, administración y actualizarse.
- una lista de órdenes (`["gmail.search", "calendar.create"]`).

Para prepararlo:

1. En Google Cloud, activar **Gmail API**, **Google Calendar API**, **Google Drive API**,
   **Google Docs API** y **Google Sheets API**.
2. En *Google Auth Platform*, tu correo como usuario de prueba.
3. Descargar el JSON del cliente OAuth (*Aplicación de escritorio*) como
   `google-cliente.json` en la raíz del proyecto.
4. `bin/gog-autorizar tu@gmail.com` (abre el navegador): pide los permisos según la
   política; al cambiarla, hay que volver a autorizar.

En modo *Prueba*, Google hace caducar la autorización cada 7 días; para evitarlo, en
*Google Auth Platform → Público* publicar la app (para uso propio no hace falta que
Google la verifique: sale el aviso de «app no verificada» y se continúa).

Los servidores MCP oficiales de Google (`gmailmcp`/`drivemcp.googleapis.com`) se
probaron y se descartaron: exigen el *Google Workspace Developer Preview Program*,
cerrado a cuentas personales.

Otros LLM son plugins en `server/llm/`:

```python
# server/llm/mi_llm.py
from llm import INSTRUCCIONES, LLM, registrar

@registrar("mi-llm")
class MiLLM(LLM):
    async def nueva(self): ...           # conversación nueva
    async def responder(self, texto):    # trozos de la respuesta según llegan
        yield "Hola"
    async def cerrar(self): ...          # opcional, al parar el servidor
```

y `--llm mi-llm [--llm-modelo …]`.

## Voz (TTS)

Cada frase de la respuesta se sintetiza en cuanto se completa y suena mientras
llega la siguiente. Tocar la pantalla lo calla. El volumen se normaliza al máximo.

Para no oírse a sí mismo: mientras habla no escucha, ni durante `--eco` segundos
después (1,2 por defecto: su voz tarda en ir a la tablet, sonar y volver por el
micro). Y si aun así lo que oye en los segundos siguientes es un trozo corto de lo
que acaba de decir («¿Algo más?» tras «¿Necesitas algo más?»), lo descarta.

Dos plugins con las voces de macOS (Mónica por defecto; `say -v '?' | grep es_`
para ver otras):

- **`avspeech`** (por defecto): AVSpeechSynthesizer en un puente Swift que mantiene
  la voz cargada, ~50 ms por frase. Si descargas la versión mejorada de una voz en
  Ajustes → Accesibilidad → Contenido leído, la usa.
- `macos`: `say`, ~600 ms por frase (arranca cada vez).

Otros motores son plugins en `server/tts/` con `sintetizar(texto)` → int16 mono a
48 kHz.

```
uv run server/main.py --voz Eddy --velocidad 200   # otra voz, más rápida
uv run server/main.py --tts macos                  # con `say`
uv run server/main.py --tts ninguno                # solo texto
```

## Estructura

- `server/main.py` — HTTP, señalización (`/offer`), monitor (`/video.mjpg`, `/estado`).
- `server/transporte.py` — sesión WebRTC: pistas, DataChannel `control`, último fotograma.
- `server/audio.py` — PCM mono 48 kHz; `Altavoz` es la pista de salida.
- `server/cerebro/` — `loro.py` (Fase 1), `oido.py` (VAD + STT), `transcriptor.py` (Fase 2), `asistente.py` (Fase 3).
- `server/stt/` — plugins de voz a texto.
- `server/despertar/` — plugins de palabra de activación.
- `server/llm/` — plugins de LLM; `permisos.py`, qué MCP y comandos puede usar Claude.
- `bin/gog`, `bin/gog-autorizar` — Google (gog) para Jarvis con su política, y su autorización.
- `bin/jarvis-confirmar` — hook que pide tu «sí» antes de cualquier acción que escriba.
- `server/tts/` — plugins de voz.
- `server/plugins.py` — registro común de plugins; `server/texto.py`, utilidades de texto;
  `server/swift.py`, compila los puentes en Swift de los plugins.
- `web/` — la página del móvil (JS sin bundler, Chrome ≤ 119) y el monitor.

Próximas fases: ojos (captura bajo demanda), cara, y después app nativa con libwebrtc contra el mismo servidor.
