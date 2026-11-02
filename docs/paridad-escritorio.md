# Paridad de la app de Windows y Linux y del admin web con la app del Mac

La referencia es la app del Mac (`apps/mac/Sources/AnyAssistant`: menú en App.swift, instalador en
Setup.swift, Ajustes, Dispositivos, Voces, Correo, Temas, «Conectar otro dispositivo», ServerUnavailable;
textos en `apps/mac/Resources/{en,es}.lproj/Localizable.strings`). La app de Windows y Linux es
`apps/desktop` (Electron: `main.js` menú y ventanas, `setup.js` + `setup.html` el instalador,
`server.js` el servidor, `bonjour.js` los servidores de la red, `locales/{en,es}.json` sus textos) y
muestra el admin web (`plugins/admin/web`, textos en `plugins/admin/locales/{en,es}.json`, «admin_page»)
y la página de temas (`plugins/themes`).

Dos tests mantienen la paridad de los textos (`tests/test_admin_web.py`): cada texto que piden el admin
web y la app de escritorio existe en sus locales, y donde la clave inglesa es la del Mac, el castellano es
exactamente el del Mac.

## Menú (bandeja)

| Diferencia encontrada | Qué se ha hecho |
|---|---|
| Estado del servidor sin símbolo y con otras palabras: «Arrancando…», «Parado», «Ha fallado (…)»; nunca «Todavía no está instalado». | El estado con una marca delante (✓ ■ … ⚠ ⬇: la bandeja no dibuja SF Symbols) y las palabras del Mac: «Funcionando», «Apagado», «Encendiéndose…», «Se ha parado. Lo vuelvo a encender…», «Todavía no está instalado». |
| Dispositivos conectados: «?» cuando no tienen nombre; el LLM «openai» como «OpenAI». | «un dispositivo» como en el Mac; nombre · habitación · LLM; clic abre Dispositivos. Sin icono por tipo: el menú de bandeja no tiene SF Symbols y haría falta un juego de iconos propio (el admin web sí los dibuja). |
| «Arrancar» / «Parar». | «Encender» / «Apagar» / «Reiniciar», en el mismo lugar y con los mismos estados (apagado o fallido: Encender; encendiéndose: Apagar; funcionando: Reiniciar y Apagar). |
| No había «Escuchar en este dispositivo». | Añadido: con la casilla activada, la cara (la página) sigue abierta oculta y pulsa «Empezar» sola, así el micrófono del equipo escucha aunque no se vea; cerrar la ventana solo la oculta. Desactivada, solo escucha mientras se ve. |
| «Permitir el micrófono» / «Permitir la cámara» sin «…» en la clave. | Las claves del Mac («Allow the microphone…»), sin «…» en el menú como hace el Mac (función M). |
| «Temas» abría la página sin estar instalado. | Igual que el Mac: solo con el servidor funcionando. |
| «Conectar otro dispositivo» y «Administrar» abrían el admin entero; no existían «Dispositivos» ni «Ajustes». | Como el Mac: «Conectar otro dispositivo», «Dispositivos» (separador) «Registro», «Ajustes», «Volver a configurar», «Abrir al iniciar sesión». «Administrar» desaparece. |
| No había «Volver a configurar…». | Añadido: abre el instalador (fase de bienvenida), como «Install steps again…» del Mac. |
| El menú existía antes de instalar. | Sin instalar (ni conectado a otro servidor) no hay icono en la bandeja: solo la ventana del instalador; cerrarla sin instalar cierra la app. |
| Como cliente de otro servidor no había menú propio. | Menú de cliente como el del Mac: «Conectado a %s» / «Buscando el servidor…» / «El micrófono está apagado», Mostrar/Ocultar a Eva, Escuchar en este dispositivo, «Usar este dispositivo como servidor…», Abrir al iniciar sesión, Salir. |
| Como cliente de otro servidor seguía escuchando durante una llamada: nadie miraba el micrófono de este equipo (con su propio servidor lo hace el plugin «microphone-busy»). | Lo mira la app, como `MicrophoneWatch.swift` del Mac: `microphone.js` (las comprobaciones del plugin pasadas a JS: el registro de consentimiento de Windows con `reg query`, `pw-dump` o `pactl` en Linux; la propia app fuera), una vez por segundo; ocupado 1 s pausa, libre 2 s reanuda. Su página se lo dice al servidor como el Mac («paused» con la app, «listening») y su micrófono manda silencio mientras; el menú dice «En pausa: Zoom usa el micrófono». Solo si ese servidor tiene `pause_when_microphone_busy` (de `/config`). Tests: `node --test apps/desktop/test/`, con las muestras de los del plugin. |
| «Reinicia» por voz en Windows: `os.execv` es otro proceso y la app perdía el servidor que vigila (lo daba por caído y lo adoptaba si respondía a los 4 s). | La app pide al servidor que, al reiniciarse, termine con el código 75 (`ANYASSISTANT_RESTART_EXIT`) y lo arranca de nuevo; no cuenta como fallo («ha fallado» es 3 veces en 5 minutos). En macOS y Linux sin la app (el Mac, systemd, `bin/anyassistant`) sigue con `os.execv`. |
| Un servidor adoptado (systemd, otro arranque) que se paraba seguía como «Funcionando». | Se comprueba cada 5 s, como el Mac cada 2 s: pasa a «Apagado» y vuelve a «Funcionando» si responde. |
| El idioma se decidía antes de que Electron lo supiera (`app.getLocale` antes de `ready`): podía salir en inglés en un sistema en castellano. | Los textos se cargan al estar lista la app. |
| Ajustes con ⌘, en el Mac. | No: un menú de bandeja no tiene atajos. |

## Instalador (primera vez)

| Diferencia encontrada | Qué se ha hecho |
|---|---|
| Electron instalaba en silencio al arrancar (uv hacía el Python y el servidor descargaba los modelos), sin preguntar nada ni mostrar el progreso. | Ventana del instalador (`setup.js`, `setup.html`, 520 × 560, no redimensionable) con las fases del Mac: bienvenida con el icono, «Instala el servidor de AnyAssistant en este dispositivo o conéctate a otro servidor.», «Instalar», «Personalizar…», «Conectarse a otro servidor…» y el pie «Durante la instalación se descargan los modelos de voz…»; «Preparando la instalación…» (uv sync); «Personalizar» con las preguntas del instalador (`setup --list --json`: título, ayuda, opciones o texto) y «Abrir AnyAssistant al iniciar sesión»; «Instalando…» con la barra y los pasos según llegan (`setup --json`, un evento por línea, `--skip service --skip connect` como el Mac); «Instalación completada» / «Instalación completada con errores», «AnyAssistant ya está en marcha en este dispositivo.», «Cerrar» y «Conectar otro dispositivo». |
| `bin/anyassistant setup` es un script de shell: no existe en Windows. | La app lanza el instalador con el Python del programa (`server/installer.py`), igual que hace el script; así funciona en Windows y Linux. |
| No había forma de usar el equipo solo como cliente de otro servidor. | «Conectarse a otro servidor…»: «Servidores en esta red» (lista Bonjour, `bonjour.js`: consulta mDNS sin biblioteca), «Otro servidor…» (Host y Puerto, «El nombre o la dirección IP del servidor.»), «Código de emparejamiento» si el servidor lo pide, «Emparejar». La cara pasa a ser la de ese servidor (emparejada con la cookie de la sesión de la app). Errores: «El código no es correcto o ha caducado.», «El servidor no responde. Comprueba que AnyAssistant esté en marcha y que este dispositivo esté en la misma red.». |
| El Mac copia el programa con `install.sh`. | En Electron el programa ya lo copia la app al arrancar (empaquetada); «Preparando la instalación…» hace su Python con uv. |

## Ventanas

| Diferencia encontrada | Qué se ha hecho |
|---|---|
| Una sola ventana «AnyAssistant» con todo el admin. | Ventanas como las del Mac: «Ajustes» (940 × 640, mín. 780 × 520), «Dispositivos» (520 × 460), «Conectar otro dispositivo» (680 × 500), «Temas» (1100 × 780), la cara (480 × 640). La página se abre con `?window=settings\|devices\|pair` y muestra solo esa parte, sin cabecera. |
| El título de la ventana lo ponía la página («Eva · Administración»). | El título es el de la ventana (el de la app), como en el Mac. |
| Con el servidor caído, Chromium mostraba su página de error. | `unavailable.html`, como ServerUnavailable: en el centro «El servidor no responde» y qué hacer: «El servidor de AnyAssistant está detenido.» + «Iniciar el servidor» si está apagado, o «Comprueba que AnyAssistant esté en marcha.» + «Reintentar». Cuando el servidor vuelve, las ventanas recargan solas. |
| «Conectar otro dispositivo…» en Dispositivos cambiaba la misma ventana. | Abre la ventana «Conectar otro dispositivo», como el Mac. |

## Admin web (lo que ven las ventanas, y la página desde otro navegador)

| Diferencia encontrada | Qué se ha hecho |
|---|---|
| Ajustes como página con buscador y grupos apilados; Plugins como otra sección del menú. | Barra lateral como la del Mac: el buscador arriba, «General» con sus secciones (Asistente, Voz, Privacidad y seguridad, Servidor) y «Plugins»; la búsqueda encuentra opciones y plugins estén donde estén. En la página completa, además, «Conectar otro dispositivo», «Dispositivos» y «Administradores». |
| Texto de entrada «Se guardan al cambiarlos…» y «Lo que puede hacer…» que el Mac no tiene. | Quitados. |
| Pastilla «reinicia» en cada opción. | «Se aplica al reiniciar.» tras la ayuda, como el Mac. |
| Aviso «Algunos cambios se aplican al reiniciar.» + «Reiniciar ahora». | «Algunos cambios se notarán cuando lo reinicies.» + «Reiniciar». |
| Plugins por tipo en otro orden y con otros títulos («Cómo funciona», «LLM», «Voz», «Librerías», «Palabra de activación»). | El orden y los títulos del Mac: Funciones, Habilidades, Bibliotecas, Cerebro, Modelos de lenguaje (LLM), Reconocimiento de voz, Voces, Palabra para despertarlo, Detección de voz. Estado «Activado/Desactivado» y chevron en cada fila; candado (SVG) en los de seguridad en vez de la pastilla «seguridad». |
| Página de un plugin: interruptor «Activado» aparte de la descripción; cuentas de correo y voces en la misma página. | Como el Mac: el interruptor junto al nombre y la descripción (y lo que le falta, en naranja); «Cuentas de correo» y «Voces conocidas» como páginas propias con su botón de volver; las opciones atenuadas con el plugin desactivado. |
| Al apagar un plugin bloqueado: «Es un plugin de seguridad, o uno que necesita para funcionar. ¿Desactivarlo igualmente?». | «¿Seguro que quieres apagarlo?» con el mensaje del Mac según el caso («Protege tu asistente…» o «AnyAssistant lo necesita para funcionar bien.»). |
| Dispositivos sin icono, pastilla «Conectado». | Icono por tipo (iPhone, iPad, Mac, Apple Watch, Android, PC, otro: SVG en línea), punto verde si está conectado, chevron; la página del dispositivo con el icono grande, nombre y estado, como la hoja del Mac. |
| «Olvidar» preguntaba «¿Olvidar este dispositivo? Si el emparejamiento está activado, necesitará un código nuevo.» | «¿Olvidar este dispositivo?» + «Se olvida aquí; si vuelve a conectarse, será un dispositivo nuevo.» |
| Un nombre repetido salía como `alert`. | «Ya hay otro dispositivo con ese nombre.» bajo los campos, como el Mac; «No se ha podido guardar.» si falla otra cosa. |
| La calibración que no arranca salía como `alert` con el texto del servidor. | Junto al campo: «No se ha podido empezar la calibración. Activa el plugin «Calibración».» (el Mac lo dice como pregunta: ver «Abierto»). |
| Voces: «Nadie todavía: … escucha a todos», «Empezar a aprender», frases y antigüedad en cada persona, formulario de aprender siempre visible. | Textos del Mac: «Nadie aún: mientras no conozca a nadie, hace caso a todos.», pie «Qué exige una voz conocida está en Ajustes → Seguridad…», sección «Aprender una voz» con «Una guía te muestra cada frase…» y el botón «Aprender una voz…» que abre la guía (dispositivo «Elige uno», nombre, «Empezar»); «Frase %d de %d», «Escuchando en el dispositivo…», «Cerrar» y «Aprender otra» al terminar. Solo el nombre (y los avisos de volver a aprender) en cada persona. |
| Correo: «Ninguna todavía.», «Contraseña (de aplicación, si tiene)», «Nombre (opcional)», «Añadir», confirmación al quitar, `alert` con los problemas. | Textos y campos del Mac: «Aún no hay cuentas. Gmail no va aquí…», el pie sobre avisos y Llavero, Dirección / Nombre («como la llamarás: «Trabajo»») / Contraseña («una contraseña de aplicación, si tu proveedor las tiene») / Servidores (IMAP, SMTP, Usuario) y «Probar y añadir» (activo con dirección y contraseña); «Probar» y «Quitar» sin confirmación; «Sin contraseña» en rojo, ✓ si funciona; los problemas bajo la cuenta o el formulario, en rojo. «Importar de este Mac…» no aplica (Cuentas de Internet de macOS). |
| Conectar otro dispositivo: «No hace falta código: el emparejamiento está desactivado.», «Ese código no vale (o ha caducado): pide otro.». | Los del Mac: «No hace falta código: cualquier dispositivo de tu red puede conectarse.», «El código no es correcto o ha caducado.». |
| Catálogo de la comunidad sin traducir (19 textos solo en inglés) y sin la frase «Un plugin se ejecuta en este servidor con tus permisos.». | Traducidos con los textos del Mac; «Volver a cargar el catálogo» como enlace. |
| «falta instalar:» era «no se encuentra el programa:». | El del Mac. |
| Si el servidor no respondía, la página se quedaba a medias sin decir nada. | «El servidor no responde» centrado, «Comprueba que AnyAssistant esté en marcha.» y «Reintentar» (como ServerUnavailable). |
| Errores de guardado de opciones como `alert`. | Bajo el campo, en rojo. |
| Inglés del admin distinto del inglés del Mac («Pair a device» vs «Connect another device»). | El inglés del Mac donde la clave es la misma. |
| Sección «Administradores» y pantalla de código de administración, que el Mac no tiene. | Se quedan: solo existen en la web (quién puede administrar desde otro navegador). |
| Cabecera «Eva · equipo · versión» con «Reiniciar». | Se queda en la página completa (es útil desde otro navegador); en las ventanas de la app no se muestra, como en el Mac (reiniciar está en el menú). |

## Temas

Sin diferencias: las dos apps abren la misma página `/themes` en una ventana (1100 × 780). El Mac añade «Abrir los temas en el navegador» en el menú Ver (una app de bandeja no tiene barra de menús).

## Abierto (decisión del usuario)

- Dos textos del Mac son preguntas, contra el criterio de afirmar qué hacer: «¿No se instala solo? En Android, ve a Ajustes → Seguridad…» y «No se ha podido empezar la calibración: ¿está activado el plugin «Calibración»?». En el admin web y la app se dicen como afirmación («Si no se instala solo, en Android ve a Ajustes → Seguridad → Instalar desde almacenamiento y elige AnyAssistant.crt.», «No se ha podido empezar la calibración. Activa el plugin «Calibración».»); el Mac no se ha tocado.
- Iconos por tipo de dispositivo en el menú de bandeja: harían falta imágenes PNG propias (claro y oscuro) para Windows y Linux.

## Sin comprobar en Windows y Linux reales

Probado en este Mac con `npm start` contra un servidor de desarrollo (puerto 8081, datos en una carpeta
aparte): instalador completo (bienvenida, Bonjour con dos servidores, código erróneo, servidor
inaccesible, preguntas, instalación con sus pasos, fin), la cara oculta escuchando, las ventanas de
Ajustes, Plugins, Correo, Voces, búsqueda, Dispositivos y Conectar otro dispositivo, y «El servidor no
responde» con «Reintentar». Queda por ver en los sistemas de destino: la bandeja y sus marcas, el
uv empaquetado haciendo el Python la primera vez, «Abrir al iniciar sesión» (registro en Windows,
`autostart` en Linux), el servicio systemd, las respuestas mDNS unicast de Avahi y del Bonjour de
Windows, y los ajustes de privacidad de Windows.
