# TODO

## Lo siguiente

Probándose ahora (1 nov): la versión 0.1.0 de Windows y Linux (github.com/studiolxd/anyassistant/
releases: el instalador .exe, el AppImage y el .deb), y la app de Android en un Android 8.

- [ ] **Registrar tu voz** («Eva, aprende mi voz», o Ajustes → Voces) y afinar `voice_match`
  (abajo, «Quién habla»): hoy no hay ninguna voz aprendida, así que escucha a cualquiera.
- [ ] **Licencia del repositorio** (público en github.com/studiolxd/anyassistant, sin licencia:
  se puede leer, no reutilizar): MIT, Apache 2.0… o ninguna, a propósito.

## Las apps

- [ ] **iPhone y iPad**: instalar la última versión en el iPhone 16 Pro (el arreglo de los
  textos); subir a TestFlight para el iPhone 7 (iOS 15) y el iPad (iOS 17) y probarlas allí;
  el sonido de las alarmas, el del tema (hoy el del sistema); los recordatorios, ¿alarma
  (AlarmKit, como ahora) o notificación normal?; un modo demo para la revisión de la App Store
  (el revisor no tiene tu Mac), solo si se publica fuera de TestFlight.
- [ ] **Android**: probarla en un Android 8 real (el micrófono y la cancelación de eco,
  encontrar el Mac por Bonjour, la alarma con la pantalla bloqueada, la cámara); publicarla
  (Google Play, o el APK firmado para instalar a mano).
- [ ] **El Mac** (servidor y cliente): hablarle de verdad desde «Mostrar a Eva»; su diseño e
  icono; encontrar el servidor de otro Mac con Bonjour (hoy, su dirección a mano); campos de
  ajustes como es debido para las opciones que son listas o JSON (hoy, un campo de texto).
- [ ] **El Apple Watch**: los avisos en la muñeca (alarmas, agenda, «la cocina dice…», con
  vibración: notificaciones push); fuera de casa (el Mac accesible desde fuera: Tailscale…);
  una complicación para la esfera y el botón Acción.
- [ ] **La tablet con Android 4.4** (la página web): comprobar que el vídeo silencioso
  (`web/awake.mp4`) mantiene la pantalla encendida; si no, hacerlo algo mayor (un vídeo de
  1 px quizá no cuente como visible).
- [ ] **Tele**: no por ahora (sin micrófono que puedan usar las apps); si acaso, Android TV
  como pantalla y altavoz, con la app de Android.

## El instalador

- [ ] **Un paquete de versión** (install.sh copia el checkout de git, o la copia de la app):
  ahora que el repositorio es público, las versiones de GitHub (Releases) con lo que lleva
  cada una; el paso de registro de la voz (`@installer.device`) cuando exista ese plugin.

## El servidor en Windows y Linux

Corre en el Mac, Windows y Linux (1 nov; versión 0.1.0 publicada). Cada plugin dice en
`plugin.json` dónde corre (`needs.system`, `needs.arch`, paquetes con marcador de sistema), y
cada equipo elige los motores que tiene. Cómo se hizo cada pieza:

| Pieza | En el Mac | En Windows y Linux |
|---|---|---|
| Reconocimiento de voz | Parakeet y Whisper en MLX (Apple Silicon) | `stt-parakeet-onnx` (el mismo Parakeet v3 en ONNX, CPU; CUDA si hay NVIDIA) y `stt-faster-whisper` |
| Palabra de activación | `wake-whisper` sobre MLX | que use el Whisper que haya (faster-whisper tiny/base); openWakeWord ya vale |
| Voz | AVSpeech y `say` | `tts-kokoro` (Kokoro-82M en ONNX, voces en español) y `tts-piper` (más ligero, para una Raspberry) |
| LLM | Claude (CLI), Hermes, Apple (modelo del Mac) | Claude y Hermes valen; Apple no (`llm-fallback` ya lo salta) |
| Correo | contraseñas en el llavero (`security`) | `keyring`: el Administrador de credenciales de Windows, Secret Service en Linux |
| Bonjour (`anyassistant.local`) | `dns-sd` | `zeroconf` en Python (vale también en el Mac: una sola implementación) |
| HTTPS | el nombre con `scutil` | `socket.gethostname()` |
| Alarma sin dispositivos | `afplay` y `say` en el Mac | la voz del plugin de TTS por los altavoces del equipo, o nada |
| Voces del sistema (`tools-system`) | `say -v ?` | las voces del plugin de TTS |
| Servicio | `launchctl` (`bin/anyassistant`) | Linux: unidad `systemd --user`; Windows: la app de la bandeja lo arranca (como la del Mac), y al iniciar sesión |
| Rutas | `~/Library/Application Support`, `~/Library/Caches` | Windows: `%APPDATA%`, `%LOCALAPPDATA%`; Linux: `~/.local/share`, `~/.cache` (XDG) |
| App | la de la barra de menús (servidor y cliente) | una app de bandeja para los dos (abajo) |

**La app de Windows y Linux** (servidor y cliente, como la del Mac): Electron. Arranca el
servidor, tiene el menú de la bandeja, y su cara es la página que ya existe (`/`, las cuatro
temas), con micrófono, cámara y cancelación de eco de Chromium, iguales en los dos sistemas.
Lo que hoy dibuja la app del Mac en SwiftUI (ajustes, dispositivos, emparejar con QR, correo,
voces) se hace una vez como páginas web de administración (`/admin`, solo desde el propio
equipo), y valen para los dos y para un Linux sin pantalla. Descartados: Tauri (en Linux usa
WebKitGTK, con WebRTC flojo) y Compose Desktop (reutilizaría los temas de Android, pero
Java no tiene cancelación de eco).

**Por fases** (cada una se puede usar al acabar):

- [x] **1. Núcleo portable** (1 nov): rutas XDG e instalación con systemd en Linux;
  `zeroconf` y `keyring` fuera del Mac (dependencias con marcador de sistema en
  `plugin.json`); PyTorch solo CPU; la alarma sin `afplay`; reiniciar sin señales
  (`web.stop`); los motores por defecto, los que tenga cada equipo. Probado en Ubuntu 24.04
  (OrbStack). Los tests corren en GitHub Actions en Linux, Windows y macOS en cada subida
  (encontraron 5 fallos de Windows y del certificado HTTPS, arreglados).
- [x] **2. Motores portables** (1 nov): `stt-parakeet-onnx` (Parakeet v3 int8, 0,1–0,3 s por
  frase en CPU; con el respaldo de Whisper si se va al inglés), `stt-faster-whisper` (CPU
  int8, o NVIDIA si tiene sus librerías), `tts-kokoro` (Dora en español, ~4× tiempo real),
  `wake-whisper` con faster-whisper fuera del Mac. Probado en Ubuntu: «¿Qué hora es?» por
  `/talk` → «Son las 4 y 48 de la tarde» con la voz de Kokoro.
- [ ] **2b. Lo que queda de los motores**: probarlo todo en tu Windows y tu Linux (en
  curso); Claude Code allí (las preguntas abiertas); `tts-piper` (más ligero, para una
  Raspberry); `set_voice` con las voces de Kokoro (hoy, solo las del Mac); en Windows,
  reiniciar por voz con la app de bandeja (hoy `os.execv`, que cambia de proceso).
- [x] **3. Linux sin pantalla** (1 nov): `install.sh` y el servicio de systemd; la
  administración web en `/admin` (emparejar con QR, dispositivos, ajustes, plugins, voces,
  correo, administradores), en el idioma del servidor. Desde el propio equipo, o desde un
  navegador con un código de administración (`bin/anyassistant admin-code` por SSH, o la
  página): de un solo uso, 5 minutos, cookie con su hash en `admins.json`, revocable; una
  tablet emparejada para hablar no puede administrar. Falta: probarla en tu Linux.
- [x] **4. La app de bandeja** (1 nov, `apps/desktop`, Electron 44): adopta el servidor que ya
  funcione (el servicio de systemd) o arranca el suyo con uv y lo vigila (si se cae, otra vez;
  tres veces en 5 minutos, «ha fallado»); lo para limpio (`/admin/stop`); «Mostrar a Eva» (la
  página, con micrófono y cámara solo para 127.0.0.1), «Emparejar un dispositivo…» y
  «Administrar…» (`/admin`); abrir al iniciar sesión (Windows, y `~/.config/autostart` en
  Linux). Probada en el Mac (arranca su servidor, carga la cara, al salir lo para). Falta:
  probarla en tu Windows y tu Linux.
- [x] **5. Paquetes, sin firmar** (1 nov): el instalador de Windows (.exe, NSIS, para tu
  usuario), el AppImage y el .deb, con el programa y uv dentro (sin Node ni uv aparte), hechos
  en GitHub Actions («packages»: a mano, o una etiqueta v* hace una versión en Releases).
  **v0.1.0 publicada** (1 nov), con la app del Mac también (`AnyAssistant-0.1.0-mac.dmg`, Apple
  Silicon, firmada y notarizada). La siguiente: subir `version` en `apps/desktop/package.json`,
  `git tag v0.1.1 && git push origin v0.1.1`.
- [ ] **5b. Lo que queda de los paquetes**: firmar el de Windows cuando lo instale más gente
  (Azure Artifact Signing a nombre de Studio LXD, ~10 $/mes; confirmar que admite empresas de
  España); actualizarse sola (hoy, instalar la versión nueva encima); versiones ARM (Windows
  en ARM, Raspberry Pi); la app del Mac en Releases cada versión sin hacerlo a mano (hoy: `apps/mac/build.sh --release` en este Mac y `gh release upload`; en Actions haría falta el certificado como secreto).


## Varios dispositivos, lo siguiente

- [ ] **Afinar quién contesta**: el margen (1,5 s) y la comparación por volumen, con más
  uso real (el log dice `heard it louder` / `not woken`).

## Quién habla

- [ ] **Afinar la huella de voz con voces reales** (`voice_match`, 0,5): el log da la
  puntuación de cada frase. Con voces sintéticas: la misma ~0,7–0,8, otra ~0,0–0,5.
- [ ] **La memoria de cada persona**: «hechos solo de lo que dice el usuario», pero en una
  casa de varios se mezclan; ahora que sabe quién habla, cada uno los suyos.

## Tomar la iniciativa

- [ ] **Más avisos**: los de Home Assistant cuando lo haya. La base ya está (`notices`).

## Casa y multimedia

- [ ] **Home Assistant** (cuando lo tengas instalado; HomeKit, no): luces, persianas,
  climatización (lo primero que se le pide a un asistente de voz en casa). El plan:
  1. Para el LLM, el MCP de Home Assistant (lo conectas tú a los LLM, como Holded):
     ya entiende sus áreas y lo expuesto a Assist. Las áreas son nuestras habitaciones,
     y el LLM ya sabe desde cuál le hablas. Falta la regla de confirmación: luces,
     persianas y clima sin «sí»; cerraduras, garaje y alarma con él (el hook ve los
     argumentos).
  2. Órdenes rápidas sin LLM, con su API («enciende la luz», «sube la persiana», «pon
     la calefacción a 21»): en menos de un segundo, y aunque falle Claude.
  3. Avisos de Home Assistant («la lavadora ha terminado») dichos donde estés.
- [ ] **Música, radio, podcasts**: solo reproduce su voz y sus sonidos. Antes, valorar
  opciones para que suene en el dispositivo donde la pides (no solo en el Mac: Spotify
  Connect, AirPlay, por la página…).

## Calidad de la conversación

- [ ] **Interrumpirle sin decir su nombre**: mientras habla no escucha (eco), así que
  solo funcionan «Jarvis, para» o un toque. Necesita una cancelación de eco mejor que
  la de la tablet; lo que más haría que pareciera una conversación, y lo más difícil.
  Ahora es más alcanzable: las apps nativas (iPhone, Mac, Android) usan la cancelación de
  eco del sistema, mucho mejor que la del navegador: probar a escuchar mientras habla solo
  en ellas.
- [ ] **Palabra de activación**: seguir vigilando falsos positivos y negativos (31 oct:
  28 activaciones, una falsa, corregida; no se encontraron fallos). Un nombre en el
  idioma del usuario llega con el nuevo nombre de la app (`name`).

## Mantenimiento

- [ ] **Puentes Swift en macOS 27**: `LanguageModelSession.GenerationError` está
  deprecado (apple_bridge.swift); el sintetizador de AVSpeech avisa sobre el main
  actor. La app del Mac compila en modo de lenguaje Swift 5 (la concurrencia estricta
  de Swift 6: pendiente).
- [ ] **Un test end-to-end inestable**: una vez, la palabra de activación no oyó nada en
  35 s con la voz sintética (test_memory_with_claude); pasó al repetirlo.

## Hecho

- [x] **Gemini CLI y OpenCode con tus cuentas** (1 nov, `llm-gemini`, `llm-opencode`, por ACP:
  `server/llm/acp.py`): «usa Gemini», «usa OpenCode». Un proceso por dispositivo, una sesión por
  conversación, la respuesta en trozos, la imagen con la pregunta. Sus servidores MCP y las
  herramientas de Eva; sin sus herramientas de archivos ni terminal (Gemini: una política de
  administrador; OpenCode: todo pregunta y Eva lo rechaza). Antes de lo que cambia algo, el
  agente espera mientras Eva pregunta en voz alta, y tu «sí» deja pasar esa llamada. Con la
  cuenta gratuita de Google, Gemini CLI ya no funciona («migra a Antigravity»): lo dice.
- [x] **Codex con tu suscripción de ChatGPT** (1 nov, `llm-codex`): «usa Codex». Un proceso
  `codex app-server` por dispositivo, un hilo por conversación, la respuesta en trozos y la
  imagen de la cámara con la pregunta. Sus servidores MCP y las herramientas de Eva; antes de
  cada herramienta MCP que cambia algo, Codex pregunta a Eva y espera tu «sí» (el mismo de
  siempre, `confirmation`). Sin terminal ni archivos (sandbox de solo lectura, carpeta vacía).
- [x] **Una sola app de Mac, servidor y cliente** (1 nov, `apps/mac`): la cara del asistente
  en una ventana («Mostrar a Eva»), su micrófono, altavoz y cámara (los mismos archivos que la
  app del iPhone: `Sources/AnyAssistant/Client`, enlaces a `apps/ios/Sources`), hablando con
  el servidor del propio Mac sin emparejar; o, en un Mac sin servidor, solo cliente del de otro
  Mac (dirección y código, en la instalación). Fuera el cliente Mac Catalyst.
- [x] **La app del Apple Watch** (1 nov, `apps/watch`, `talk-api`): toca y habla; la frase al
  Mac (`POST /talk`), la respuesta en texto y voz; emparejada con el código de 6 dígitos;
  HTTPS fiándose solo de la autoridad del Mac. Un dispositivo más (su conversación, su voz).
- [x] **Quién habla** (1 nov, `voices`): la huella de voz de cada persona («aprende mi voz»
  en el dispositivo, o desde la app); `voice_check` all (solo voces conocidas), actions (solo
  el «sí») u off; un «sí» desconocido se rechaza; el LLM sabe quién habla.
- [x] **Una conversación por dispositivo** (1 nov): cada uno con su LLM (hasta
  `conversations`, 2; con 1, de una en una); dos personas en dos habitaciones no se cortan.
  Sus herramientas actúan en su dispositivo (`/mcp?device=…`).
- [x] **Temas para verlos** (el antiguo lab, ahora `themes`, `/themes`): todos los estados de
  cada uno, desde el menú de la app («Temas…»); solo para ver. Sin comprobador.
- [x] **Toma la iniciativa** (1 nov): avisos de la agenda («Dentro de 10 minutos:
  dentista», `calendar-notices`) y el resumen de la mañana («buenos días» o al parar la
  primera alarma: la fecha y los festivos, el tiempo, la agenda y cuántos emails sin leer,
  `morning`), sin el LLM (`google`: bin/gog). Con educación (`notices`): no de noche
  (`quiet_hours`), no mientras alguien le habla, con un tono suave antes.
  Y al llegar un email («Tienes un email nuevo de Ana», `email-notices`): los de Principal;
  de quién, también el asunto, o solo cuántos.
- [x] **Otras cuentas de correo** (`mail`, IMAP y SMTP): avisos y la cuenta de la mañana
  también de ellas; el LLM las lista, lee y envía (con tu «sí»). `bin/anyassistant mail add`,
  la contraseña en el Llavero; o en la app (Ajustes → Cuentas de correo), que también
  importa las del Mac (sus servidores; la contraseña la escribes).
- [x] **El menú de la app con varios dispositivos**: cuántos y cuáles, y con cuál hablas.
- [x] **Varios dispositivos a la vez** (1 nov, probado con el iPad y la tablet) (`hub.py`,
  `devices`): contesta el que te oyó y, si
  te oyen dos, el que lo oyó más fuerte; una conversación a la vez; cada uno con nombre y
  habitación (por voz o en la ventana «Dispositivos» de la app). Alarmas, temporizadores y
  recordatorios suenan en todos (`alarm_rings`, por defecto) o donde se pusieron, «… en la cocina» por
  voz; si ese no está, en todos; se paran en cualquiera. Mensajes de una habitación a otra
  («dile a la cocina que bajo ya», `tell_device`): se dicen allí, sin tono. El LLM sabe
  por qué dispositivo y en qué habitación le hablas («aquí»).
- [x] **HTTPS en local** (`https`): una autoridad propia que cada dispositivo instala una
  vez (`/https/ca.crt`, el QR de la app); la página en https://anyassistant.local, sin
  puerto (443) y sin el flag de Chrome; http://anyassistant.local (80) lleva a ella, y la
  página por HTTP desde otro dispositivo (la tablet por su IP) también. Los permisos de
  micrófono y cámara se piden antes de la pantalla completa (en ella, Safari del iPad no
  los muestra).
- [x] **Los ajustes de la app, traducidos también en sus opciones** (`choices.<opción>`).
- [x] **Cada plugin trae sus propios textos** (31 oct): su nombre, descripción,
  opciones, pasos del instalador, lo que dice y sus palabras, en su `locales/`; el
  núcleo se queda solo con los suyos y lo compartido. Un test comprueba que el español
  de cada plugin tiene su inglés.
- [x] **Listas y notas** (`skill-lists`): «añade leche a la lista de la compra»,
  cualquier lista, «toma nota de que…»; `lists.json`; también como herramientas del LLM.
- [x] **El tiempo** (`skill-weather`): «¿qué tiempo hace?», «¿va a llover mañana?», «el
  tiempo en Málaga», de Open-Meteo (gratis, sin cuenta); tu ciudad en `location`.
- [x] **Plan B** (`llm-fallback`): cuando el LLM no puede contestar (sin red, un límite
  de uso, sesión cerrada) contesta el modelo local de Apple, y lo dice; los LLM lanzan
  `llm.Unavailable`.
- [x] **Siempre encendido** (`always-on`, desactivado por defecto): no se duerme solo.
- [x] **Alarmas hasta que se paren**: `ring_seconds` a 0 suena hasta que alguien la
  pare (como mucho 30 min).
- [x] **AnyAssistant para el Mac** (31 oct): una app de la barra de menús que instala
  (con lo que viene, o paso a paso) y ejecuta el servidor (con su permiso de Red Local;
  el servidor sigue a la app), empareja dispositivos (QR + código), ajustes y plugins
  (siempre al día: también cambian por voz), en inglés y español (Localizable.strings;
  los textos del servidor también traducidos). Firmada con el Developer ID de Studio
  LXD: `apps/mac/build.sh` mientras se desarrolla, `--release` notarizada para
  compartirla.
- [x] **Bonjour** (`bonjour`): el servidor se anuncia como `_anyassistant._tcp`.
- [x] **admin**: ajustes y plugins para la app (`/admin/…`, solo desde el Mac).
- [x] **La página reintenta de verdad**: un watchdog reinicia un intento de conexión que
  se cuelga.
- [x] **update y uninstall**: `bin/anyassistant update` (nunca a una versión anterior
  salvo con `--force`) y `uninstall` (tus datos solo si lo dices). Terminal y app a la
  vez: start/stop ceden a la app cuando es ella la que ejecuta el servidor.
- [x] **La app es AnyAssistant** (`bin/anyassistant`, `ANYASSISTANT_HOME`…, el servidor
  MCP `anyassistant`, también en la config de Hermes); el asistente sigue siendo Jarvis
  por defecto.
- [x] **Instalador (terminal)**: install.sh + `bin/anyassistant setup`, pasos del núcleo
  y de los plugins (preguntas, tareas, tareas en el dispositivo), launchd; probado en
  una carpeta limpia.
- [x] **Todo es un plugin** (31 oct): el núcleo solo los encuentra, los carga y los une
  (kernel, web hooks, eventos, tipos). Emparejamiento, confirmación, memoria, ojos, la
  página y los temas, sonidos, tocar para despertar, monitor, lab, servidor MCP,
  intérprete, los cerebros, «vete a dormir» y «para»… cada uno un plugin, con lo que
  necesita en plugin.json.
- [x] **Temas**: la pantalla como HTML + CSS que cualquiera puede hacer (bloques,
  estados, variables en vivo, opciones, textos, sonidos); ojos, orbe, minimal y mesilla;
  un lab.
- [x] **No toda frase es para él**: una ventana de `follow_up` (20 s) en lugar de 2
  minutos escuchando, e `ignore_others`: el LLM contesta `<silence>` a lo que no es
  para él.
- [x] **Hermes con las herramientas del asistente**: el servidor MCP en la config de
  Hermes; el «sí» lo pide el propio servidor, así que vale también para Hermes.
- [x] **Skills sin LLM**: hora, fecha, temporizadores, alarmas, recordatorios, sumas,
  unidades y volumen; el modelo de Apple como intérprete opcional; también como
  herramientas del LLM.
- [x] **Ojos, segundo paso**: una foto a resolución completa para leer (1200×1600 en la
  tablet); Hermes también ve (se le pide con «mira», «lee»…).
- [x] **Memoria, más**: compactada por el LLM a partir de 50 hechos; revisada también por
  el modelo de Apple (se le escapan algunos hechos nuevos; a Claude no); las
  correcciones actualizan el hecho.
- [x] **Elegir el LLM**: `get_llms`/`set_llm` y «usa Claude» / «cambia a Hermes».
- [x] **Memoria**: el plugin `memory`, `"memory": "explicit"|"auto"`; `memory.json`, una
  revisión de cada conversación cuando se duerme (auto).
- [x] **Ojos**: el plugin `eyes`; con Claude, por palabras («¿qué ves?», «lee esto») o
  por decisión propia (Read sobre la imagen del momento).
- [x] **Emparejamiento** (el plugin `pairing`; `bin/anyassistant pair|unpair`, el QR de
  la app).
- [x] **Interrumpir por voz**: «Jarvis, para» o «Jarvis, ¿y mañana?» mientras habla.
- [x] **Latencia**: un proceso de Claude de repuesto siempre listo (~1,5 s hasta la
  primera palabra en lugar de 2,5–3). El modelo sigue siendo un ajuste (`llm_model`).
- [x] **Grabaciones**: borradas las antiguas de depuración; `record` solo si se pide.
  Transcripciones en el log solo con `log_transcripts`.
- [x] **Idiomas**: inglés como base y español en `locales/`; `language` o por voz.
- [x] **Ajustes**: `settings.json`; cara, voz, nombre e idioma también por voz con tu «sí».
- [x] **Sus propias herramientas (MCP)**: el servidor es un servidor MCP (ajustes,
  memoria, cámara, recargar, reiniciar), usado por Claude y Hermes.
- [x] **Tests automáticos**: pytest en `tests/` (`uv run pytest`; `-m e2e` para el
  servidor real).

## Aplazado

- **Apps nativas para Android, iOS, Android TV, Windows** (el Apple Watch antes; el papel
  de cliente del Mac con la app del Mac). La de Android: sin el flag de Chrome, encuentra el
  servidor con Bonjour y se empareja con el QR; comprobar si llega a la tablet antigua.
- **Bilingüe a la vez**: contestar en el idioma en que se dice cada frase; cuando todo
  lo demás funcione.

La IP fija del Mac importa menos ahora (Bonjour, el QR de la app); publicar la app de
Google es cosa de quien lo instale (ver el README).
