# TODO

## Lo siguiente

- [ ] **La app de Android**: sin el flag de Chrome; encuentra el servidor con Bonjour
  (`_anyassistant._tcp`) y se empareja con el QR de la app del Mac. Comprobar antes si
  puede llegar a la tablet antigua (Android 4.4) o si esa se queda con la página en Chrome.
- [ ] **AnyAssistant para el Mac, lo siguiente**: su diseño e icono; el papel de cliente
  (hablarle desde el propio Mac; conectarse al servidor de otro Mac, encontrado con
  Bonjour); campos de ajustes como es debido para las opciones que son listas o JSON
  (hoy, un campo de texto).
- [ ] **Instalador, lo siguiente**: un tarball de release (install.sh copia el checkout
  de git, o la copia de la app); el paso de registro de la voz (`@installer.device`)
  cuando exista ese plugin.

## Varios dispositivos, lo siguiente

- [ ] **Una conversación por dispositivo**: hoy, una a la vez (el LLM es uno: un proceso
  de Claude); si hablan dos personas en dos habitaciones, la segunda corta la primera.
  Un LLM por conversación, con su coste.
- [ ] **Afinar quién contesta**: el margen (1,5 s) y la comparación por volumen, con más
  uso real (el log dice `heard it louder` / `not woken`).

## Skins

- [ ] **Un mejor comprobador de skins**: hoy `skin check` comprueba en concreto el
  Chrome 81 de la tablet antigua. Comprobar contra los navegadores/dispositivos que
  soportamos (una lista de objetivos, p. ej. «Chrome ≥ 81, Android WebView ≥ …»), o
  quitarlo.
- [ ] **El lab como vista previa oficial de skins** (un plugin, o parte de la página):
  ver y editar skins, no solo previsualizarlas. Su diseño, más adelante.

## Quién habla

- [ ] **Identificación del hablante** (una huella de voz, p. ej. embeddings ECAPA): el
  «sí» que confirma acciones de escritura (un email, Holded con gog en "all") puede
  venir de cualquiera, un invitado, un niño o la tele; ignore_others ayuda, pero decide
  el LLM, no es una barrera. Exigir una voz conocida para esos «sí». La memoria
  también: «hechos solo de lo que dice el usuario», pero ¿qué usuario? En una casa de
  varios, se mezclan los hechos de todos. Registro: el paso del instalador hecho en el
  dispositivo (`@installer.device`).

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
- [ ] **Música, radio, podcasts**: solo reproduce su voz y sus sonidos; controlar
  Spotify o Apple Music en el Mac.

## Calidad de la conversación

- [ ] **Interrumpirle sin decir su nombre**: mientras habla no escucha (eco), así que
  solo funcionan «Jarvis, para» o un toque. Necesita una cancelación de eco mejor que
  la de la tablet; lo que más haría que pareciera una conversación, y lo más difícil.
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
  página y las skins, sonidos, tocar para despertar, monitor, lab, servidor MCP,
  intérprete, los cerebros, «vete a dormir» y «para»… cada uno un plugin, con lo que
  necesita en plugin.json.
- [x] **Skins**: la pantalla como HTML + CSS que cualquiera puede hacer (bloques,
  estados, variables en vivo, opciones, textos, sonidos); ojos, orbe, minimal y mesilla;
  un lab y un comprobador.
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

- **Apps nativas para iOS, Android TV, Windows** (Android primero, arriba; el papel de
  cliente del Mac con la app del Mac).
- **Bilingüe a la vez**: contestar en el idioma en que se dice cada frase; cuando todo
  lo demás funcione.

La IP fija del Mac importa menos ahora (Bonjour, el QR de la app); publicar la app de
Google es cosa de quien lo instale (ver el README).
