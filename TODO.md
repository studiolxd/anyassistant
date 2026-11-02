# TODO

# Para publicar

- [ ] **Subir la app de iPhone y iPad a TestFlight.**
- [ ] **Probar la app en el iPhone 7** (iOS 15), desde TestFlight.
- [ ] **Hacer un modo demo para la revisión de la App Store** (el revisor no tiene tu servidor), solo si
  se publica fuera de TestFlight.
- [ ] **Publicar la app de Android** (Google Play, o el APK firmado para instalar a mano).
- [ ] **Publicar las versiones en GitHub Releases** con lo que lleva cada una (install.sh copia hoy el
  checkout de git, o la copia de la app).
- [ ] **Firmar el instalador de Windows** cuando lo instale más gente (Azure Artifact
  Signing a nombre de Studio LXD, ~10 $/mes; confirmar que admite empresas de España).
- [ ] **Que las apps se actualicen solas** (hoy, instalar la versión nueva encima).
- [ ] **Versión para Windows en ARM.**
- [ ] **Versión para Raspberry Pi** (Linux en ARM).
- [ ] **Subir la app del Mac a Releases** en cada versión sin hacerlo a mano (hoy:
  `apps/mac/build.sh --release` en este Mac y `gh release upload`; en Actions haría falta el
  certificado como secreto).

# Desarrollo

## Las apps

- [ ] **Probar la app de Android en un Android 8 real** (el micrófono y la cancelación de eco, Bonjour,
  la alarma con la pantalla bloqueada, la cámara).
- [ ] **Probar la app del Mac como cliente de otro servidor.**
- [ ] **El Apple Watch**: recibir los avisos en la muñeca (alarmas, agenda, «la cocina dice…», con
  vibración: notificaciones push).
- [ ] **El Apple Watch**: usarlo fuera de casa (el servidor accesible desde fuera: Tailscale…).
- [ ] **El Apple Watch**: una complicación para la esfera.
- [ ] **El Apple Watch**: el botón Acción.

## Diseño de las páginas web

Hoy son funcionales pero sobrias; que sigan el estilo y el vocabulario de las apps.

- [ ] **Diseñar la página de temas** (`plugins/themes`: la ventana Temas de la app del Mac, un
  WKWebView, y el navegador).
- [ ] **Diseñar la administración web** (`plugins/admin/web`: la de Windows y Linux y cualquier
  navegador).
- [ ] **Diseñar la pantalla de emparejar con el código** en la página del dispositivo (`#pair` en
  `plugins/page/web/index.html` y `system.css`).
- [ ] **Diseñar la página del QR** (`/connect`, `plugins/page/web/connect.html`).

## El instalador

- [ ] **Añadir el paso de registro de la voz** al instalador (`@installer.device`).

## Windows y Linux

Cómo se hizo: `docs/windows-y-linux.md`.

- [ ] **Probar en tu Windows** los motores, la app de bandeja y la administración web (en curso).
- [ ] **Probar en tu Linux** los motores, la app de bandeja y la administración web (en curso).
- [ ] **Hacer funcionar Claude Code en Windows** (las preguntas abiertas).
- [ ] **Hacer funcionar Claude Code en Linux** (las preguntas abiertas).
- [ ] **Añadir `tts-piper`**: una voz más ligera, para una Raspberry.
- [ ] **Elegir voz (`set_voice`) entre las de Kokoro** (hoy, solo las del Mac).
- [ ] **Poder reiniciar por voz en Windows** con la app de bandeja (hoy `os.execv`, que cambia de
  proceso).
- [ ] **Controlar el equipo sin LLM en Windows.**
- [ ] **Controlar el equipo sin LLM en Linux.**
- [ ] **Decidir qué dice la app de bandeja** cuando es cliente de otro servidor y otra app usa el
  micrófono.

## Varios dispositivos, lo siguiente

- [ ] **Afinar el margen de quién contesta** (1,5 s) con más uso real (el log dice `not woken`).
- [ ] **Afinar la comparación por volumen de quién contesta** con más uso real (el log dice
  `heard it louder`).

## Quién habla

- [ ] **Afinar la huella de voz con voces reales** (`voice_match`, 0,5; el log da la puntuación
  de cada frase; con voces sintéticas, la misma ~0,7–0,8, otra ~0,0–0,5).
- [ ] **Separar la memoria de cada persona** (en una casa de varios, los hechos se mezclan;
  ahora que sabe quién habla, cada uno los suyos).

## Casa y multimedia

Home Assistant, cuando lo tengas instalado (HomeKit, no): luces, persianas y climatización,
lo primero que se le pide a un asistente de voz en casa. Conectarlo no es desarrollo: su
servidor MCP se añade a `.mcp.json` y se permite en `permissions.json`, como Holded; lo usan los
LLM con MCP (Claude, Gemini, OpenCode), no el de Apple ni Hermes.

- [ ] **Añadir la regla de confirmación de Home Assistant**: luces, persianas y clima sin «sí»;
  cerraduras, garaje y alarma con él (el hook ve los argumentos).
- [ ] **Órdenes rápidas de Home Assistant sin LLM** con su API («enciende la luz», «sube la
  persiana», «pon la calefacción a 21»), en menos de un segundo y aunque falle Claude.
- [ ] **Decir los avisos de Home Assistant donde estés** («la lavadora ha terminado»; `notices`).
- [ ] **Valorar cómo hacer que la música suene en el dispositivo donde la pides** (no solo en el
  Mac: Spotify Connect, AirPlay, por la página…).
- [ ] **Reproducir música, radio y podcasts** (hoy solo reproduce su voz y sus sonidos).

## Calidad de la conversación

- [ ] **Afinar el eco al interrumpirle** (`listen_while_speaking`) con más uso real en cada
  dispositivo (el log da la puntuación de cada frase, «its own echo» / «not its echo»).
- [ ] **Evitar que Parakeet se pase al inglés** con frases cortas («Yeah.», «Thank you.»; docs/corpus.md).
- [ ] **No perder las primeras palabras con ruido** (0,3 s de preroll; docs/corpus.md).
- [ ] **Evitar que Whisper se invente «Gracias.»** (docs/corpus.md).
- [ ] **Juntar una pregunta partida por una pausa** («la caída del imperio» … «romano de
  Occidente»): si el segundo trozo llega mientras piensa la respuesta al primero, una sola
  respuesta a los dos.
- [ ] **Vigilar los falsos positivos y negativos de la palabra de activación** (31 oct: 28
  activaciones, una falsa, corregida).
- [ ] **Contestar en el idioma en que se dice cada frase** (bilingüe a la vez).

## Mantenimiento

- [ ] **Pasar la app del Mac a Swift 6** (hoy compila en modo de lenguaje Swift 5).

# Hecho

- [x] **Los puentes de Swift para versiones anteriores** (2 nov): se compilaban para la versión
  del Mac donde se hacían (macOS 27) y no se abrían en 14 a 26; ahora, la voz para macOS 14 y el
  modelo de Apple para macOS 26.
- [x] **El modelo de Apple sin `GenerationError`** en macOS 27 (`LanguageModelError`), con el de
  antes en macOS 26; el puente de AVSpeech sin avisos (también en Swift 6).
- [x] **El test end-to-end inestable**: cada prueba empieza con silencio, para que el oído aprenda
  el ruido antes del primer «Hey Jarvis».

- [x] **Apps nativas** para Android, iPhone, iPad, el Apple Watch y Windows y Linux (la app de
  bandeja); el Mac como cliente con su app. La de Android encuentra el servidor con Bonjour y se
  empareja con el QR.

- [x] **Alarmas con el sonido del tema y recordatorios como notificación** (2 nov): en el
  iPhone, el iPad y Android las alarmas y los temporizadores suenan con la alarma del tema
  (`/alarm.wav`); los recordatorios son notificaciones normales. La página de temas deja
  escuchar los sonidos de cada tema.
- [x] **La tablet con Android 4.4** (2 nov): la pantalla se mantiene encendida con NoSleep.js
  (la política de la página bloqueaba su vídeo `data:`).
- [x] **Interrumpirle sin decir su nombre** (2 nov): activado por defecto
  (`listen_while_speaking`); su eco se reconoce por el volumen y por sus palabras.
- [x] **El Mac**: su icono y su asistente de instalación; encontrar otro servidor por Bonjour;
  las opciones de tipo diccionario con su editor (y plugins, correo y voces en sus páginas).

- [x] **Licencia del repositorio**: MIT (`LICENSE`).

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

# Descartados

- **Tele**: sin micrófono que puedan usar las apps (si acaso, Android TV como pantalla y
  altavoz, con la app de Android).
