# El micrófono cuando otra app lo usa, y lo que suena en el propio dispositivo

Un estudio, sin código, de dos funciones de audio en cada plataforma de AnyAssistant, para decidir
cómo construirlas. Fecha: 2 de noviembre de 2026.

- **Función A — pausar la escucha mientras otra app usa el micrófono** (una llamada, una
  videoconferencia), para no transcribirla; reanudar cuando acabe.
- **Función B — ignorar lo que sale del propio dispositivo** (su voz, música, la tele por el
  ordenador), para poder interrumpirle sin decir su nombre y que no reaccione a lo que él mismo
  reproduce.

Referencia: minion, del mismo autor (`/Users/suvi/Dev/lab/minion`, Rust, solo macOS):
`src/microphone.rs` (quién más graba, por CoreAudio, macOS 14 o posterior, opción
`pause_when_microphone_busy`, activada) y `src/loopback.rs` (un *process tap* de CoreAudio sobre la
salida del sistema, macOS 14.2 o posterior, que compara la envolvente de volumen de la salida con la
del micrófono; un prototipo, desactivado por defecto: `ignore_own_audio`).

Donde no he podido comprobarlo lo digo: «sin verificar». La estimación de esfuerzo es orientativa:
*pequeño* (un día), *medio* (dos a cuatro días), *grande* (una semana o más), contando pruebas en
dispositivos reales.

---

## 1. Cómo captura y reproduce cada cliente hoy

| Cliente | Captura | Reproducción | Cancelación de eco | Cómo llega al servidor |
|---|---|---|---|---|
| **Mac** (`apps/mac`, cliente de su propio servidor o de otro Mac; macOS 14 o posterior, `Package.swift`) | `AVAudioEngine.inputNode` con *voice processing* (`apps/ios/Sources/Audio.swift`, enlazado en `apps/mac/Sources/AnyAssistant/Client`) | `AVAudioPlayerNode` en el mismo motor | La del sistema (AUVoiceIO): cancela lo que el propio motor reproduce | WebSocket `/stream` (plugin `stream-api`), PCM 16 bits mono 48 kHz |
| **iPhone y iPad** (`apps/ios`, iOS 15 o posterior) | Lo mismo, con `AVAudioSession` `.playAndRecord` + `.voiceChat` (no mezclable: sin `.mixWithOthers`); modo en segundo plano «audio» | Igual | La de iOS (voice processing) | Igual |
| **Android** (`apps/android`, Android 8 o posterior, `minSdk 26`) | `AudioRecord` con `VOICE_COMMUNICATION`, modo `MODE_IN_COMMUNICATION`, `AcousticEchoCanceler` y `NoiseSuppressor` si el teléfono los tiene (`Audio.kt`); servicio en primer plano de tipo `microphone` | `AudioTrack` con `USAGE_VOICE_COMMUNICATION` por el altavoz | La del teléfono (varía mucho por modelo) | Igual |
| **Página web** (`plugins/page/web/app.js`: tablets y móviles viejos, Safari, Chrome) | `getUserMedia({audio: {echoCancellation, noiseSuppression, autoGainControl}})` | `<audio id="speaker">` con la pista remota | La del navegador (en Chromium, solo del audio que la propia página reproduce; en Safari, la del sistema) | WebRTC (Opus) a aiortc, `POST /offer`; mensajes por el *data channel* |
| **Windows y Linux** (`apps/desktop`, Electron) | La misma página en Chromium (`contextIsolation`, `sandbox`, sin *preload*), con permisos `media` solo para el propio origen (`main.js`) | Igual | La de Chromium | Igual, desde `127.0.0.1` |
| **Apple Watch** (`apps/watch`) | Pulsar para hablar, `POST /talk` con un WAV | | No procede | `talk-api` |

Ninguna app sabe hoy si otra usa el micrófono, ni qué suena en el dispositivo. Lo que ya hay:

- **iOS** (`Audio.swift`): observa `AVAudioSession.interruptionNotification` pero solo reacciona al
  `.ended` (reinicia el audio); el `.began` no se trata ni se comunica al servidor. También
  `AVAudioEngineConfigurationChange` (auriculares, ruta) → reinicio.
- **Android** (`Link.kt`, `Audio.kt`): nada sobre interrupciones ni silenciado; no pide foco de audio.
- **Mac**: «Escuchar en este Mac» (`Eva.swift`, `listening`) apaga el micrófono a mano.
- **Página**: ni `mute`/`unmute` de la pista ni `visibilitychange` para el audio (solo para el
  *wake lock*).

### Lo que hace el servidor con su propio eco

Todo está en `plugins/brain-assistant/__init__.py` y `plugins/brain-transcriber/ear.py`:

- **Sordo mientras habla**: `_deaf()` es verdad mientras `speaker.speaking` y durante `echo_guard`
  segundos (1,2 por defecto; opción en `server/options.py`) después del último sonido. En
  `Ear._window` la VAD se reinicia y no se transcribe nada. Con `stream-api`, «hablando» se estima
  por la duración del PCM enviado (`Voice.until`), no por lo que el dispositivo reproduce de verdad.
- **Su nombre mientras habla** (`voice_interrupt`, activado): el motor de palabra de activación
  sigue escuchando (`wake.continuous`) y `_interrupt()` para, salvo que lo oído sea en un 60 % o más
  palabras de lo que está diciendo (`saying`): su propia voz diciendo su nombre no cuenta.
- **Eco tardío**: `_is_echo()` descarta frases de 5 palabras o menos que sean un trozo de lo que
  acaba de decir (`said`) si empezaron a menos de `ECHO_WINDOW` = 2,5 s del último sonido.
  `tests/test_echo.py` lo cubre.
- **Entre dispositivos**: `hub.claim` no despierta a uno si otro está hablando (su voz diciendo su
  nombre, oída en la habitación de al lado); el que oyó más alto responde.
- **El LLM calla** (`ignore_others`) cuando lo oído claramente no es para él (la tele, una llamada),
  y el plugin `voices` (`voice_check: all`) solo escucha voces conocidas. Son hoy la única defensa
  frente a la tele o la música en la habitación.
- **Parrot** (`brain-parrot`) ni siquiera escucha mientras repite: «la cancelación de eco de la
  tablet no basta» (README).

El TODO ya lo tiene apuntado como lo más difícil y lo que más haría que pareciera una conversación:
«Interrumpirle sin decir su nombre»; y sugiere probar a escuchar mientras habla solo en las apps
nativas, que usan la cancelación de eco del sistema.

---

## 2. Lo que enseña minion

**`microphone.rs` (función A, macOS):**

- La señal correcta es *¿hay otro proceso grabando?*, no *¿qué app está delante?* (Teams delante
  sin llamada no es llamada; Meet en una pestaña de atrás sí). macOS 14 publica un objeto por
  proceso con audio (`kAudioHardwarePropertyProcessObjectList`, `'prs#'`) y cada uno dice si tiene
  un flujo de entrada en marcha (`kAudioProcessPropertyIsRunningInput`, `'piri'`), su PID
  (`'ppid'`) y su *bundle ID* (`'pbid'`). Comprobado en las cabeceras del SDK local
  (`AudioHardware.h`); el macOS 27 de este equipo las tiene.
- Hay que filtrar los demonios de Apple: `com.apple.CoreSpeech`, `siri.wakeupd`, Control Center,
  Universal Control… encienden la entrada a cada rato (176 pausas en un día de registro). Se
  excluye todo `com.apple.*` salvo las apps que una persona usa para llamar o grabar (FaceTime,
  QuickTime, Notas de voz, Safari). Un proceso sin *bundle ID* cuenta como persona.
- Nunca desde el *callback* de audio (leer propiedades puede bloquear): se consulta cada 250 ms
  desde el bucle ocioso y se cachea un segundo. La condición debe mantenerse un rato antes de
  pausar (histéresis), porque los cambios de un instante son normales.
- Ningún permiso: lee propiedades del HAL. Sin API antes de macOS 14: la opción no hace nada y lo
  dice una vez.

**`loopback.rs` (función B, macOS):**

- Un *process tap* (`CATapDescription`, `AudioHardwareCreateProcessTap`, macOS 14.2 o posterior,
  comprobado en `AudioHardwareTapping.h`) sobre toda la salida del sistema, en mono, envuelto en un
  dispositivo agregado privado cuyo subdispositivo es la salida actual; se lee el flujo de
  *entrada* de ese agregado con un IOProc. Con `TapAutoStart` solo corre mientras algo suena: el
  silencio llega como ausencia de *callbacks*, no como ceros (el anillo rellena el hueco con el
  reloj). Un Mac callado no cuesta nada.
- Se compara por **envolventes**, no por muestras: el micrófono oye la versión de la habitación
  (retrasada, filtrada, más baja, mezclada). Envolvente = log-RMS por ventanas de 20 ms (50 por
  segundo); correlación normalizada de la frase oída con los últimos 12 s de salida, buscando el
  desfase en ±400 ms alrededor del retardo esperado; umbral 0,6. Además, un **arranque** de la
  salida (silencio → fuerte, un *chime* de notificación) veta la frase en la VAD, en sus primeros
  200 ms.
- Se abre **después** del micrófono (CoreAudio serializa la creación de IOProcs en el cliente).
- Permiso: macOS lo pone tras un aviso de privacidad la primera vez
  (`NSAudioCaptureUsageDescription` en el Info.plist, macOS 14.2 o posterior; sin la clave, TCC
  deniega en silencio). Se concede **por binario**: recompilar lo invalida. Minion no confirmó bajo
  qué entrada de «Privacidad y seguridad» aparece.
- Desactivado por defecto: es un segundo flujo de audio siempre abierto, y la comprobación de voz ya
  atrapa la mayoría de casos.

Las dos partes de minion están probadas con funciones puras (caché, filtro de demonios,
envolventes, arranques) y un solo test que toca CoreAudio.

---

## 3. Función A: pausar cuando otra app usa el micrófono

### Resumen

| Plataforma | ¿Posible? | API (versión mínima) | Permiso | Fiabilidad | Esfuerzo |
|---|---|---|---|---|---|
| macOS (app del Mac) | Sí, como minion | Objetos de proceso de CoreAudio (macOS 14; la app ya exige 14) | Ninguno | Alta, filtrando los demonios de Apple | Medio |
| iOS/iPadOS | Sí, pero lo hace iOS: nos interrumpe | `AVAudioSession.interruptionNotification` (.began/.ended); `CXCallObserver` (iOS 10) como apoyo | Ninguno extra | Alta para llamadas y apps no mezclables; nula para apps mezclables | Pequeño |
| Android | Sí, lo hace Android: nos silencia | `AudioRecord.registerAudioRecordingCallback` + `isClientSilenced` (API 29, Android 10); `AudioManager.mode` | Ninguno extra | Alta en Android 10 o posterior; en 8 y 9 el sistema ni deja grabar al segundo | Pequeño |
| Windows (app Electron) | Sí, por fuera de la página | Registro `CapabilityAccessManager\ConsentStore\microphone` (Windows 10 1903 o posterior); alternativa WASAPI `IAudioSessionManager2` (Vista, nativo) | Ninguno (HKCU) | Buena; sin verificar con cada app (Teams empaquetado, navegadores) | Medio |
| Linux (app Electron) | Sí, por fuera de la página | PipeWire `pw-dump` (nodos `Stream/Input/Audio` en `running`); PulseAudio `pactl list source-outputs` | Ninguno | Buena en PipeWire; sin verificar los nombres de propiedades | Medio |
| Página web (navegador) | No del todo | Eventos `mute`/`unmute` de `MediaStreamTrack`; `ended`; ceros digitales | Ninguno | Baja y desigual (sin verificar por navegador) | Pequeño |

Lo común a todas: el servidor necesita un **estado «en pausa»** por dispositivo (apartado 5). Sin
él, aunque el cliente deje de mandar audio, la cara no explica nada y el reloj de `follow_up`
sigue corriendo.

### macOS (la app del Mac como cliente)

- **API**: la misma que minion, desde Swift con la API C de CoreAudio: `AudioObjectGetPropertyData`
  sobre `kAudioObjectSystemObject` → lista de procesos → por cada uno `'piri'`, `'ppid'`, `'pbid'`.
  `Package.swift` ya pide macOS 14, así que no hay caso «sin API». Comprobación cada 250 ms a 1 s
  desde un `Timer` en `Link`/`Eva` (nunca desde el *tap* del `inputNode`), con caché de un segundo,
  excluyendo nuestro PID y los demonios de Apple (copiar la lista y los tests de minion).
- **Histéresis**: pausar si lleva ocupado 1 s; reanudar si lleva libre 2 s.
- **Qué hacer al pausar**: parar la captura (`audio.stop()` deja de leer el micrófono y suelta el
  punto naranja), mantener el WebSocket (la cara y la voz siguen: una alarma debe sonar) y mandar
  `{"type": "paused", "why": "microphone", "app": "us.zoom.xos"}`; al reanudar, `audio.start` y
  `{"type": "listening"}`. La barra de menús puede decir «En pausa: Zoom usa el micrófono» igual
  que hoy dice «El micrófono está apagado».
- **Permisos**: ninguno. Sin aviso.
- **Fiabilidad**: alta. Casos raros: la página abierta en Chrome en el mismo Mac contaría como «otro»
  (Safari está en la lista de apps de persona de minion; Chrome no es de Apple y cuenta siempre):
  aceptable, es lo que pasa cuando se abre una reunión en el navegador. El `voices` del servidor
  (WeSpeaker en el Mac) no graba.
- **Alternativa si no**: `kAudioDevicePropertyDeviceIsRunningSomewhere` (muy antigua) dice si el
  dispositivo de entrada está en uso en algún proceso, sin decir cuál; solo sirve mientras nosotros
  no capturamos. No hace falta.
- **Esfuerzo**: medio. Unas 150 líneas de Swift (la traducción de `microphone.rs`) más el estado
  en el servidor.

### iOS y iPadOS

- **No hay API para saber qué app graba**, y no la habrá (el punto naranja es para la persona).
  Pero nuestra sesión es `.playAndRecord` + `.voiceChat` **no mezclable**: cuando llega una
  llamada de teléfono, FaceTime, WhatsApp o cualquier app activa una sesión no mezclable, iOS nos
  **interrumpe**: `AVAudioSession.interruptionNotification` con `.began`, el motor se para y el
  servidor deja de recibir audio. Hoy eso ya ocurre, pero sin avisar a nadie; con `.ended` (y
  `.shouldResume`) `Audio.swift` reinicia.
- **Construir**: tratar `.began` (`audio.stop()`, `{"type": "paused", "why": "interrupted"}`) y en
  `.ended` reanudar y `{"type": "listening"}`. Apoyo: `CXCallObserver` (CallKit, iOS 10) para saber
  que hay una llamada en curso (teléfono, FaceTime y VoIP integradas con CallKit) y poder decir
  «llamada» en vez de «otra app». Sin permisos nuevos.
- **Límites**: una app que grabe con `.mixWithOthers` (poco común: Notas de voz no lo es) convive
  con nosotros sin interrumpir; no lo sabremos. En segundo plano, reactivar la sesión tras una
  llamada puede fallar hasta volver al frente (hilos de los foros de Apple); el `.ended` a veces
  llega tarde o no llega: conviene reintentar al volver al frente (`didBecomeActive`), como ya hace
  `restartAudio`.
- **Fiabilidad**: alta para lo que importa (llamadas). **Esfuerzo**: pequeño.

### Android

- **Android 10 o posterior** (API 29) reparte el micrófono: «dos apps ordinarias nunca capturan a
  la vez» y «una llamada siempre recibe el audio»; la que pierde sigue grabando pero **recibe
  ceros** (silenciada). Nosotros capturamos con `VOICE_COMMUNICATION`, que es «sensible»: tiene
  prioridad sobre una app ordinaria con fuente normal (una grabadora de notas se quedaría ella sin
  audio) y pierde frente a una llamada (`MODE_IN_CALL`/`MODE_IN_COMMUNICATION` de otra app) y
  frente a otra app sensible más reciente (una videollamada de WhatsApp).
- **API**: `AudioRecord.registerAudioRecordingCallback(executor, callback)` **antes** de
  `startRecording()`; en `onRecordingConfigChanged`, `audioRecord.activeRecordingConfiguration?.isClientSilenced`
  (API 29). Para Android 8 y 9 (API 26–28): no hay silenciado; el segundo en llegar no puede
  grabar (en 9, una app sin primer plano recibe silencio), así que si otra app quiere el
  micrófono es ella la que falla, no nosotros; no hay nada que detectar. También
  `AudioManager.getActiveRecordingConfigurations()` (API 24) lista las grabaciones activas del
  dispositivo (sin verificar qué detalla de las de otras apps) y `AudioManager.mode` dice si hay
  llamada. `TelephonyManager` necesita `READ_PHONE_STATE`: descartado.
- **Construir**: al quedar silenciados, mandar `paused` (motivo «microphone»); al dejar de estarlo,
  `listening`. Seguir mandando los ceros no hace daño (la VAD no se activa), pero el servidor
  transcribiría en vano si hubiera ruido residual y la cara no diría nada. Opcional, buen vecino:
  si `getActiveRecordingConfigurations` muestra otra app ordinaria grabando con fuente normal,
  pausar nosotros para no silenciarla (sin verificar que se vean).
- **Permisos**: ninguno nuevo. **Fiabilidad**: alta en Android 10 o posterior. **Esfuerzo**:
  pequeño.

### Windows (app de Electron)

- **La página no puede saberlo**; el proceso principal de Electron o el servidor (Python, en la
  misma máquina) sí:
  - **Registro** (sin API pública, Windows 10 1903 o posterior): bajo
    `HKCU\Software\Microsoft\Windows\CurrentVersion\CapabilityAccessManager\ConsentStore\microphone`
    hay una clave por app empaquetada y, bajo `NonPackaged`, una por ejecutable (ruta con `#`);
    cada una con `LastUsedTimeStart` y `LastUsedTimeStop` (FILETIME); **`LastUsedTimeStop == 0`
    significa «en uso ahora»**. Es lo que lee Windows 11 para el icono del micrófono en la barra.
    Hay que excluir nuestro propio ejecutable (Electron: la página lo mantiene en uso). Lectura en
    Python con `winreg` (biblioteca estándar) cada segundo, o desde Node con `reg query`.
  - **WASAPI** (nativo, desde Vista): `IMMDeviceEnumerator` → dispositivo de captura (`eCapture`)
    → `IAudioSessionManager2::GetSessionEnumerator` → sesiones con `GetState() == AudioSessionStateActive`
    y `GetProcessId()` distinto del nuestro. Más fiel (dice si de verdad hay flujo) pero necesita
    un *addon* nativo o un ayudante en C#; más trabajo.
- **Construir**: detección en el **servidor** (plugin, apartado 5), aplicada a los dispositivos
  conectados desde `127.0.0.1` (la página de la app de escritorio); el servidor deja de oír ese
  dispositivo y su cara dice «En pausa». No hace falta tocar la página ni Electron en la primera
  versión. Más adelante la página puede parar la pista (`track.enabled = false`) al recibir
  `{"type": "pause"}` para soltar el micrófono.
- **Permisos**: ninguno (HKCU). **Fiabilidad**: buena para Teams, Zoom y navegadores; sin verificar
  si todas las apps de escritorio escriben la clave (deberían: es el sistema de consentimiento) ni
  el comportamiento cuando la app está silenciada dentro de la llamada (la clave sigue «en uso»:
  pausaríamos igual, que es lo deseado). **Esfuerzo**: medio (más por probar en Windows que por el
  código).

### Linux (app de Electron)

- **PipeWire** (lo normal hoy): `pw-dump` da el grafo en JSON; los nodos con
  `media.class = "Stream/Input/Audio"` y `state = "running"` son apps grabando, con
  `application.name` y `application.process.id` (nombres sin verificar: comprobar en un `pw-dump`
  real). Excluir el Chromium de nuestra app (su audio corre en un proceso auxiliar con otro PID:
  filtrar por `application.process.binary` o `application.name`, sin verificar). **PulseAudio** (o
  `pipewire-pulse`): `pactl list source-outputs` (texto; `-f json` desde PulseAudio 16, sin
  verificar) con `application.process.id`. Sondeo cada segundo desde el servidor (Python,
  subproceso) o suscripción con `pw-mon`/`pactl subscribe`.
- **Construir**: el mismo plugin del servidor que en Windows, otra fuente. En un servidor Linux sin
  pantalla ni micrófono no hay nada que detectar.
- **Permisos**: ninguno. **Fiabilidad**: buena. **Esfuerzo**: medio, compartido con Windows.

### Página web (un navegador cualquiera)

- No hay API para saber qué más usa el micrófono. Señales indirectas:
  - **`MediaStreamTrack` `mute`/`unmute`**: la especificación lo prevé para «una llamada entrante
    en un sistema móvil»; Chrome en escritorio refleja el silenciado del sistema; en **Android
    Chrome** y **Safari de iOS** no he encontrado confirmación (sin verificar): probar en la tablet.
    Cuando la pista acaba (`ended`), reconectar (ya se hace al caer la conexión).
  - **Ceros digitales**: en Android, la app silenciada recibe ceros exactos; el servidor puede
    detectar N segundos de muestras a cero (no «silencio bajo», cero exacto) y marcar el
    dispositivo «micrófono silenciado». Vale para cualquier cliente sin tocarlo. Ojo con Opus: tras
    la codificación los ceros dejan de ser exactos salvo con DTX; en la página, mejor detectar
    `track.muted` y avisar; en `stream-api` (PCM crudo) los ceros sí llegan intactos.
- **Construir**: en `app.js`, escuchar `mute`/`unmute` y `visibilitychange` y mandar
  `paused`/`listening` por el *data channel*; en el servidor, el detector de ceros para
  `stream-api`. **Esfuerzo**: pequeño. **Fiabilidad**: baja y desigual; es lo que hay. Alternativa
  real: el plugin `voices` y `ignore_others`, que ya evitan que lo oído en una llamada acabe en el
  LLM.

---

## 4. Función B: ignorar lo que suena en el propio dispositivo

Conviene separar dos cosas que hoy van juntas:

- **B1, su propia voz**: el servidor sabe **exactamente** qué está diciendo (el PCM que manda) y
  cuándo. No hace falta ninguna API del sistema: es un problema del servidor.
- **B2, otros sonidos del dispositivo**: música, un vídeo, la tele por el ordenador, el otro lado
  de una llamada. Solo el dispositivo puede saber qué suena, y no en todas las plataformas.

### B1: interrumpirle sin decir su nombre (en el servidor, para todas las plataformas)

Hoy, mientras habla, el servidor está sordo salvo para su nombre. Todas las apps nativas y Chromium
ya le quitan al micrófono (casi) toda su propia voz (cancelación de eco), así que lo que llega
mientras habla es: residuo de su voz (bajo, deformado), o una persona hablando encima.

Propuesta, calcada de minion pero con una ventaja: la referencia no hay que capturarla, **ya la
tenemos** (`Speaker.play` en `server/audio.py` y `Voice.play` en `stream-api` reciben el PCM).

1. El servidor guarda la envolvente (log-RMS cada 20 ms, 50 valores por segundo: nada de memoria)
   de los últimos 12 s de lo que ha enviado a cada dispositivo, con el instante de envío.
2. Mientras habla, `Ear` **no se reinicia**: segmenta con la VAD como siempre. Al cerrar una frase,
   antes de la STT, se compara su envolvente con la de la salida buscando el desfase en una ventana
   (retardo de reproducción del dispositivo: unos 100–300 ms en WebRTC con *jitter buffer*,
   menos en las apps; ±400 ms de búsqueda como minion, más la latencia estimada de `Voice.until`).
   Si la correlación supera el umbral (0,6 para empezar), es su eco: se descarta. Si no, es alguien
   hablando encima: **parar y transcribir** (como hoy «Jarvis, para», sin el nombre), o
   transcribir y dejar que `ignore_others` decida si era para él.
3. Lo mismo vale después de hablar (sustituye a `echo_guard` y a `_is_echo`, que se quedan como
   red de seguridad) y **entre dispositivos**: la frase de un dispositivo contra la salida de
   cualquier otro que esté sonando (dos en la misma habitación; hoy `hub.claim` solo bloquea el
   nombre). Y el **arranque** de salida (silencio → fuerte: un sonido de alarma o de tema) como
   veto en la VAD, como en minion.

Riesgos y cómo medirlos antes de construir:

- El residuo de la cancelación de eco de la **tablet** (Chromium viejo en Android 4.4–7) puede
  parecer voz y, peor, la correlación de envolventes puede fallar si la cancelación deja solo
  trozos. Por eso el TODO sugiere empezar por las apps nativas. **Primero medir**: con la opción
  `record` (ya existe: guarda todo lo que llega en WAV) grabar en cada cliente mientras habla, y
  calcular en un cuaderno cuánto residuo queda (RMS oído / RMS enviado) y qué correlación da. Es un
  día de trabajo y decide umbrales y a qué clientes se les activa.
- Una persona hablando **a la vez** que él: la envolvente mezclada se parece menos a la salida;
  bien. Una persona repitiendo lo que él dice (cosa rara) parecería eco: se descarta; aceptable.
- Ajuste: opción `listen_while_speaking` (o `voice_interrupt` con tres valores: `name`, `any`,
  `off`), por defecto solo en clientes nativos hasta que las medidas digan otra cosa; umbral oculto.

**Esfuerzo**: medio, solo Python (numpy), con tests puros como los de minion (el mismo sonido más
bajo y retrasado coincide; otro no; silencio no se juzga; la alineación se busca). Es lo que más
mejora la conversación por menos trabajo, y vale para los seis clientes a la vez.

### B2: lo demás que suena en el dispositivo

| Plataforma | ¿Posible? | API (versión mínima) | Permiso | Fiabilidad | Esfuerzo |
|---|---|---|---|---|---|
| macOS (app del Mac) | Sí, como minion | *Process tap* de CoreAudio (macOS 14.2; la app pide 14.0: `#available(macOS 14.2)`) | Aviso de privacidad la primera vez; `NSAudioCaptureUsageDescription` en `build.sh`; por binario | Buena (prototipo en minion) | Medio-grande |
| iOS/iPadOS | No | No hay captura de la salida del sistema; solo señales gruesas: `isOtherAudioPlaying`, `secondaryAudioShouldBeSilencedHint` (iOS 8) | — | — | Dejar fuera |
| Android | A medias, mala experiencia | `AudioPlaybackCaptureConfiguration` + `MediaProjection` (API 29): diálogo de «capturar pantalla» en cada sesión, notificación permanente, muchas apps se excluyen (`ALLOW_CAPTURE_BY_NONE`), las llamadas nunca | Consentimiento cada vez (Android 14 no lo recuerda) | Baja | Dejar fuera; señal gruesa: `getActivePlaybackConfigurations` (API 26) |
| Windows (Electron) | Sí, desde el servidor | WASAPI *loopback* (`AUDCLNT_STREAMFLAGS_LOOPBACK`, desde Vista): un dispositivo de entrada «(loopback)» en PortAudio; o `getDisplayMedia` + `audio: 'loopback'` en Electron | Ninguno | Buena | Medio |
| Linux (Electron) | Sí, desde el servidor | La fuente *monitor* del *sink* (`<sink>.monitor`) con `parec`/`pw-record` o PortAudio | Ninguno | Buena | Medio (compartido) |
| Página web | No | `getDisplayMedia({audio})` exige gesto y selector cada vez; sin audio del sistema en Linux, en macOS solo con Chrome 141 y macOS 14.2 o posterior; nada en móviles | — | — | Dejar fuera |

Lo común: el dispositivo (o el servidor en el equipo donde corre la app de escritorio) calcula la
**envolvente** de la salida y se la manda al servidor (`{"type": "output", "t": …, "env": […]}`,
50 valores por segundo, cada 200–500 ms); el servidor usa el **mismo comparador que B1**. No viaja
audio, solo volúmenes: nada de privacidad que explicar, y cabe por el WebSocket o el *data
channel* sin notarse.

**macOS (app del Mac)**: la traducción de `loopback.rs` a Swift con la API C
(`CATapDescription(monoGlobalTapButExcludeProcesses: [])`, `AudioHardwareCreateProcessTap`,
`AudioHardwareCreateAggregateDevice` con `kAudioAggregateDeviceTapAutoStartKey`,
`AudioDeviceCreateIOProcID`), abierta después del micrófono; envolvente en la app, al servidor.
Añadir `NSAudioCaptureUsageDescription` al Info.plist que escribe `apps/mac/build.sh` (sin ella, TCC
deniega en silencio). El aviso de privacidad lo da macOS al arrancar el agregado la primera vez;
sin verificar la entrada exacta de «Privacidad y seguridad» (en macOS 26 parece ir con «Grabación
de pantalla y audio del sistema») ni cómo se comporta con `install-dev.sh` (cada compilación es
otro binario: el permiso se pierde). Desactivado por defecto, como en minion. Sin verificar si el
*voice processing* de macOS ya cancela el audio de **otras** apps (creo que solo el del propio
motor): si lo hiciera, B2 en el Mac sobraría; se mide con `record` poniendo música antes de
construir nada.

**Windows y Linux (servidor)**: el servidor abre la entrada *loopback* o *monitor* como un flujo de
entrada normal (16 kHz mono basta para envolventes), calcula la envolvente y la asocia al
dispositivo conectado desde `127.0.0.1`. En Windows, PortAudio trae los dispositivos WASAPI
*loopback* desde la v19.7 (sin verificar que el PortAudio que empaqueta `sounddevice` los liste;
si no, `pyaudiowpatch` o un ayudante). En Linux, `parec --device=<sink>.monitor --raw` o
`pw-record` por subproceso es lo más robusto (flags sin verificar). Ningún permiso en los dos.
Hace falta porque la cancelación de eco de Chromium **no** cancela el audio de otras apps (solo lo
que la propia página reproduce): la tele por el ordenador entra entera por el micrófono.

**iOS**: no hay forma de capturar la salida del sistema (ReplayKit solo captura el audio de la
propia app o, en una extensión de emisión, la pantalla entera con UI del sistema: inutilizable).
En la práctica importa poco: nuestra sesión no es mezclable, así que Música o un vídeo paran al
arrancar nosotros, y al revés nos interrumpen (función A). Queda una señal gruesa gratis:
`AVAudioSession.isOtherAudioPlaying` / `secondaryAudioShouldBeSilencedHint`, que podría mandarse al
servidor para ser más estricto (exigir el nombre, `voice_check`). Dejar fuera por ahora.

**Android**: `AudioPlaybackCaptureConfiguration` captura solo apps con `USAGE_MEDIA/GAME/UNKNOWN`
que lo permitan, exige un `MediaProjection` con diálogo del sistema en cada sesión (y un servicio
en primer plano de tipo `mediaProjection`), pone la notificación de «emitiendo» y no captura las
llamadas. Para un asistente siempre encendido es inaceptable. Señal gruesa posible:
`AudioManager.getActivePlaybackConfigurations()` / `AudioPlaybackCallback` (API 26: nuestro mínimo)
dice **que** otra app reproduce y con qué uso, sin el audio; y la cancelación de eco del teléfono en
modo comunicación suele usar la mezcla de salida como referencia (varía por fabricante, sin
verificar). Dejar fuera; la señal gruesa, si acaso después.

**Página web**: `getDisplayMedia` necesita un gesto y un selector cada vez, y en móviles no existe.
Nada que hacer: B1 en el servidor más `voices` e `ignore_others`.

---

## 5. Lo que hace falta en el servidor y en el protocolo (común a todo)

1. **Estado «en pausa» por dispositivo** (`Ear.pause(why)` / `Ear.resume()`): descarta el audio,
   reinicia la VAD y la palabra de activación, congela el reloj de `follow_up`, y la cara muestra un
   estado nuevo `paused` con texto («En pausa: otra app usa el micrófono» / «Paused: another app is
   using the microphone»; con el nombre de la app cuando se sabe). En la página, `LOOKS_LIKE` lo
   dibuja como `asleep`; en `FaceModel.swift` y `Themes.kt`, lo mismo (`looksLike`). `hub.claim` no
   elige a un dispositivo en pausa; `notices` lo cuenta como «no escucha». Mensajes nuevos de
   `stream-api` y del *data channel*: `← {"type": "paused", "why": "microphone"|"call"|"interrupted", "app": "…"}`
   y `← {"type": "listening"}`; y hacia el dispositivo `→ {"type": "pause"}` / `{"type": "resume"}`
   cuando lo decide el servidor (Windows y Linux).
2. **Detector de ceros** en `stream-api` (N segundos de muestras exactamente cero → pausa con
   motivo «silenced»; cualquier muestra distinta de cero → reanuda).
3. **Plugin `microphone-busy`** (o dentro del núcleo, `server/`): en Windows (`winreg`) y Linux
   (`pw-dump`/`pactl`), sondeo cada segundo, aplicado a los dispositivos de `127.0.0.1`. En macOS
   no hace falta (la app lo hace), pero el mismo código con `ctypes` serviría para una página abierta
   en el navegador del propio Mac.
4. **Comparador de envolventes** (`server/echo.py` o un plugin `library`): envolvente, correlación,
   búsqueda de desfase, arranques; anillo de la salida enviada por dispositivo (B1) y de la
   envolvente recibida del dispositivo (B2). Usado por `brain-assistant` antes de la STT y, para
   los arranques, en `Ear._window`.
5. **Opciones** (`server/options.py`, con título y ayuda en `locales/en.json` y `es.json`, y en
   las de cada plugin si van en uno):
   - `pause_when_microphone_busy` (bool, activada): «Pausa con otras apps» / «Deja de escuchar
     mientras otra app usa el micrófono del dispositivo (una llamada); vuelve cuando acaba».
   - `listen_while_speaking` (bool; al principio desactivada, o activa solo en apps nativas):
     «Interrumpirle sin su nombre» / «Escucha mientras habla y para si alguien le habla encima».
   - `ignore_device_audio` (bool, desactivada): «Ignorar lo que suena en el dispositivo» / «Lo
     que el dispositivo reproduce (música, un vídeo) no cuenta como voz. Mac, Windows y Linux».
   - Umbrales (`own_audio_threshold`) ocultos o solo en `settings.json`.
   Aparecen solas en los ajustes del Mac (`Settings.swift`) y en el admin web (`admin.js`), que
   leen la lista de opciones del servidor.
6. **Tests** (`.venv/bin/python -m pytest -q`): funciones puras del comparador (las de minion
   traducidas), el estado en pausa (audio descartado, reanudación, reloj de `follow_up`), el
   detector de ceros, y en `test_echo.py` que lo de hoy sigue igual con la opción apagada.

---

## 6. Plan recomendado

**Primero (función A, lo barato y seguro):**

1. **Servidor**: el estado «en pausa», sus mensajes, la cara y el detector de ceros. *Pequeño.*
2. **iOS**: tratar el `.began` de la interrupción y avisar. *Pequeño.* **Android**:
   `registerAudioRecordingCallback` + `isClientSilenced` y avisar. *Pequeño.* Los dos los hace el
   sistema por nosotros; solo falta contarlo.
3. **Mac**: los objetos de proceso de CoreAudio en la app (traducir `microphone.rs`, con su lista de
   demonios y sus tests), histéresis, parar la captura, avisar. *Medio.* Es el único cliente donde
   hoy una llamada se transcribe sin remedio.
4. **Windows y Linux**: el plugin del servidor (`winreg`; `pw-dump`/`pactl`) para la página de la
   app de escritorio. *Medio.* Puede esperar a que la app de Windows exista como tal.
5. **Página**: `mute`/`unmute` → avisar. *Pequeño*, cuando se pruebe que los navegadores lo emiten.

**Después (función B1, lo que más se nota):**

6. **Medir** con `record` en cada cliente cuánto residuo de su voz queda y qué correlación da. *Un
   día.* Decide umbrales y clientes.
7. **Servidor**: el comparador de envolventes con la salida que él mismo envía; escuchar mientras
   habla; parar si alguien le habla encima; también entre dispositivos; los arranques como veto.
   Detrás de `listen_while_speaking`, primero en apps nativas. *Medio.* Sustituye con el tiempo a
   `echo_guard` y `_is_echo`, que se quedan de red.

**Luego, si las medidas lo piden (función B2):**

8. **Mac**: el *process tap* en la app, envolvente al servidor, `NSAudioCaptureUsageDescription`,
   desactivado por defecto. *Medio-grande.* Solo si el *voice processing* no cancela ya la música
   de otras apps (medirlo en el paso 6 poniendo música).
9. **Windows y Linux**: *loopback*/*monitor* desde el servidor, el mismo comparador. *Medio.*

**Dejar fuera**: B2 en iOS (imposible), B2 en Android por `MediaProjection` (diálogo cada vez,
notificación permanente, no captura llamadas ni la mayoría de apps de música), B2 en la página
(imposible sin gesto y selector), y las señales gruesas (`isOtherAudioPlaying`,
`getActivePlaybackConfigurations`): poco valor hasta que B1 funcione. Para la tele en la
habitación con una tablet, la defensa sigue siendo `voices` (solo voces conocidas) e
`ignore_others`.

**Dónde vive cada cosa**: la detección de «otra app usa el micrófono» en cada app nativa (Mac,
iOS, Android) y en el servidor para la página de escritorio; todo el juicio sobre el audio (eco,
interrupción, lo que suena) en el servidor, con los dispositivos mandando solo envolventes. Así
hay un comparador, unos tests y unas opciones, y los clientes cambian lo mínimo.

---

## 7. Por verificar antes o durante la construcción

- macOS: bajo qué entrada de «Privacidad y seguridad» cae el *process tap* y qué pasa con
  `install-dev.sh` (binario nuevo en cada compilación); si el *voice processing* cancela el audio
  de otras apps.
- Windows: que Teams (empaquetado y no), Zoom y Chrome escriben `LastUsedTimeStop = 0` durante la
  llamada; que el PortAudio de `sounddevice` lista los dispositivos *loopback*.
- Linux: nombres de propiedades en `pw-dump` (`media.class`, `state`, `application.process.id`,
  `application.process.binary`) y cómo aparece el Chromium de Electron; `pactl -f json`.
- Android: qué muestra `getActiveRecordingConfigurations` de otras apps; si la cancelación de eco
  del fabricante usa la mezcla de salida.
- Navegadores: si Android Chrome y Safari de iOS emiten `mute`/`unmute` en la pista cuando llega una
  llamada, o la pista acaba.
- iOS: que un `.began` llega en llamadas de WhatsApp y Zoom (sesiones no mezclables) y que la
  reactivación en segundo plano funciona tras colgar.
- El residuo de eco en cada cliente (paso 6 del plan): es lo que decide si B1 vale en las tablets.

---

## 8. Referencias

macOS

- Cabeceras del SDK local: `CoreAudio.framework/Headers/AudioHardware.h`
  (`kAudioHardwarePropertyProcessObjectList`, `kAudioProcessPropertyIsRunningInput`, `…PID`,
  `…BundleID`) y `AudioHardwareTapping.h` (`AudioHardwareCreateProcessTap`, `API_AVAILABLE(macos(14.2))`).
- Apple, *Capturing system audio with Core Audio taps*:
  <https://developer.apple.com/documentation/coreaudio/capturing-system-audio-with-core-audio-taps>
- Apple, `AudioHardwareCreateProcessTap`:
  <https://developer.apple.com/documentation/coreaudio/audiohardwarecreateprocesstap(_:_:)>
- Apple, `NSAudioCaptureUsageDescription`:
  <https://developer.apple.com/documentation/bundleresources/information-property-list/nsaudiocaptureusagedescription>
- AudioCap (ejemplo de *process tap* en Swift, con notas sobre el permiso):
  <https://github.com/insidegui/AudioCap>
- Chrome, cancelación de eco nativa de macOS:
  <https://developer.chrome.com/blog/macos-native-echo-cancellation>

iOS

- Apple, *Handling audio interruptions*:
  <https://developer.apple.com/documentation/avfaudio/handling-audio-interruptions>
- Apple, QA1882 `secondaryAudioShouldBeSilencedHint`:
  <https://developer.apple.com/library/archive/qa/qa1882/_index.html>
- Foros de Apple, reactivar la sesión tras una llamada en segundo plano:
  <https://developer.apple.com/forums/thread/813278>

Android

- *Sharing audio input* (reparto del micrófono, silenciado, `isClientSilenced`):
  <https://developer.android.com/media/platform/sharing-audio-input>
- `AudioManager.AudioRecordingCallback` (API 24):
  <https://developer.android.com/reference/kotlin/android/media/AudioManager.AudioRecordingCallback>
- `AudioPlaybackCaptureConfiguration` (API 29):
  <https://developer.android.com/reference/kotlin/android/media/AudioPlaybackCaptureConfiguration>

Windows

- `AUDIOCLIENT_ACTIVATION_TYPE_PROCESS_LOOPBACK` (Windows 10 build 20348 o posterior):
  <https://learn.microsoft.com/en-us/windows/win32/api/audioclientactivationparams/ne-audioclientactivationparams-audioclient_activation_type>
- `IAudioSessionManager2` / `IAudioSessionEnumerator`:
  <https://learn.microsoft.com/en-us/windows/win32/api/audiopolicy/nn-audiopolicy-iaudiosessionmanager2>
- El registro `CapabilityAccessManager\ConsentStore\microphone` (no documentado; discusión y
  detección de uso): <https://learn.microsoft.com/en-us/answers/questions/1193937/detect-if-user-has-muted-unmuted-microphone-in-mes>,
  <https://www.elevenforum.com/t/see-which-apps-have-accessed-your-microphone-in-windows-11.48684/>
- PortAudio con *loopback* WASAPI en Python (si `sounddevice` no lo trae):
  <https://pypi.org/project/pyaudiowpatch>

Linux

- PipeWire, uso habitual de `pw-dump`:
  <https://genio.mediatek.com/doc/iot-yocto/latest/sw/yocto/app-dev/audio/audio-common-usage.html>
- Chromium en Linux no captura el audio del sistema con `getDisplayMedia` (solo el de una pestaña):
  <https://github.com/edisionnano/Screenshare-with-audio-on-Discord-with-Linux>

Navegadores y Electron

- `getDisplayMedia` y el audio del sistema por plataforma:
  <https://blog.addpipe.com/getdisplaymedia-allows-capturing-the-screen-with-system-sounds-on-chrome-on-macos/>
- La cancelación de eco de Chromium solo cancela el audio WebRTC de la propia página:
  <https://github.com/webrtc/samples/issues/1243>
- `MediaStreamTrack` `mute`:
  <https://developer.mozilla.org/en-US/docs/Web/API/MediaStreamTrack/mute_event>
- Electron `desktopCapturer` (`audio: 'loopback'`, `NSAudioCaptureUsageDescription`, el *tap* de
  CoreAudio por defecto desde Electron 39): <https://www.electronjs.org/docs/latest/api/desktop-capturer>
