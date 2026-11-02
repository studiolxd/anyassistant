# Paridad de la app de Android con la de iPhone y iPad

Auditoría pantalla por pantalla y función por función de `apps/android` frente a `apps/ios`
(con `apps/shared/Mac.swift`), con iOS como referencia: mismas funciones, mismos flujos y mismas
palabras; Material donde iOS usa sus propios modismos. Fecha: 2 de noviembre de 2026.

Cada tabla: la diferencia encontrada → qué se hizo, o por qué no se tocó.

## Emparejamiento

| Diferencia | Qué se hizo |
|---|---|
| El código de emparejamiento era un campo de texto con espaciado; en iOS son seis casillas, una por dígito, que emparejan solas con la sexta. | Seis casillas (46 × 58, esquina 12, la siguiente marcada con el color de acento mientras se teclea) sobre un campo real invisible; empareja con el sexto dígito y «Emparejar» abajo vuelve a intentarlo. |
| Un QR escaneado o el enlace `anyassistant://connect` llevaban a la pantalla del código con el código relleno; en iOS se queda en la primera pantalla, con «Conectando con Eva…» en lugar de «Escanear código» y el error, si lo hay, bajo los servidores. | Igual que iOS: vuelve a la primera pantalla, muestra «Conectando con %s…» (nombre del asistente o host) con su rueda, y el error en rojo bajo la lista de servidores. |
| Un servidor sin código se conectaba sin señal alguna; en iOS la fila muestra una rueda mientras conecta. | Rueda al final de la fila del servidor que está conectando. |
| El error salía siempre al final de la columna, bajo todo; en iOS sustituye al texto de ayuda del paso (bajo los servidores, bajo Host y Puerto, bajo las casillas). | El texto de ayuda de cada paso deja su sitio al error, en rojo. |
| El campo Puerto de «Otro servidor» no tenía ejemplo; iOS muestra «8080» (y «anyassistant.local» en Host). | Ejemplos «anyassistant.local» y «8080». |
| «Escanear código»: la ayuda decía «…en el servidor: se conecta solo.»; iOS: «El código QR que muestra «Conectar otro dispositivo» en el servidor.» | El texto de iOS (en inglés con las comillas “ ” que usa iOS). |
| Sin permiso de cámara: «Permite la cámara para escanear el código.»; iOS: «Permite la cámara en Ajustes para escanear el código.» | El texto de iOS. |
| «Cancelar» (desde «Emparejar de nuevo») es un botón de texto en iOS y un icono de cerrar en Android; los pasos se apilan con la barra de navegación en iOS y con una barra superior con flecha atrás en Android; la acción del paso va arriba a la derecha en iOS y en un botón relleno sobre el teclado en Android. | Se deja: es el modismo de Material para el mismo flujo (lista → servidor → código, con vuelta atrás en cada paso). |
| Servidores por Bonjour, «Otro servidor…», `anyassistant://connect?host=…&port=…&code=…&name=…`, el propio QR `http://<ip>:<puerto>/connect?code=…`, «Emparejar de nuevo» con vuelta atrás y sin desemparejar hasta que el nuevo emparejamiento funciona. | Ya iguales (`Invitation` en Mac.kt es `Mac.Invitation` de Mac.swift; los intent-filters del manifiesto registran el enlace y el QR). |

## La cara y sus temas

| Diferencia | Qué se hizo |
|---|---|
| El reloj en 12 horas («clock»: «12») salía sin AM/PM; iOS usa la plantilla «hmm» (con AM/PM, como la página con `hour12: true`). | Las mismas plantillas que iOS: «hmm», «Hmm» y «jmm» por `getBestDateTimePattern`, en el idioma del servidor. |
| La foto que mira («¿qué ves?») solo se desaturaba; iOS la desatura (0,6) y la oscurece un poco (−0,1). | La misma matriz de color: saturación 0,6 y −0,1 de brillo. |
| Las líneas de temporizadores tenían siempre la misma separación; en iOS es 4 por defecto, 0 en Mesilla y 1 v en Minimal. | `TimerLines` toma la separación y cada tema pone la suya. |
| Ojos, orbe, mesilla y minimal: tamaños en v (1 % del lado corto), colores por estado, parpadeo, flotación, boca y puntos, ondas y anillo del orbe, ascua de mesilla, luz de minimal; reloj y fecha dormido en cada tema; subtítulos (24/17,6, el último entero, los anteriores atenuados); la cámara centrada bajo donde acaban cara y palabras (`FaceEndMark` ≈ `FaceEnd`), a lo sumo al 80 % de alto; la foto a 80 × 60 v y a lo sumo 45 % de alto, con barrido verde; zona segura (fondo hasta los bordes, contenido dentro). | Ya iguales, comprobados valor a valor. |
| En iOS el desplazamiento de los ojos entre estados lleva `.animation(.easeOut 0.3)` sobre un valor que cambia cada fotograma; Android cambia el fotograma directamente. | Se deja: sobre un valor continuo la animación de iOS solo añade un retardo; forma y tapas de los ojos sí se animan en Android (200 ms, como iOS). |

## El botón «Ajustes»

| Diferencia | Qué se hizo |
|---|---|
| Solo dormido o en error; sitio por la opción `settings` del tema (bottom, top, top-left, top-right, bottom-left, bottom-right); color `settings_color`, si no `accent`, si no `glow`, si no blanco; texto (cápsula, 14 medium, 0,85 sobre 0,14) o icono (`settings_style: icon`, círculo de 40); mantener pulsada la pantalla abre los ajustes siempre; dentro de la zona segura. | Ya igual. |

## Ajustes

| Diferencia | Qué se hizo |
|---|---|
| Eran un diálogo con Host solo; iOS es una hoja con secciones: interruptores, «Servidor» con Host y Puerto, «Conectar» con su rueda y el error en rojo debajo, y «Emparejar de nuevo» aparte. | Una página sobre la cara (como la hoja de iOS): «Ajustes» y «Hecho» arriba; «Seguir escuchando con la pantalla apagada», «Mantener la pantalla encendida» y su nota; «Servidor» con Host (ejemplo «anyassistant.local») y Puerto (ejemplo «8080»); «Conectar» / «Conectado» / «Conectando…» con rueda y el error en rojo debajo; «Emparejar de nuevo» en rojo, aparte. Atrás equivale a «Hecho». |
| El ejemplo del Host era «Vacío: lo encuentra solo (o 192.168.1.10)»; iOS «anyassistant.local». | El de iOS (el host vacío sigue funcionando: Bonjour y después anyassistant.local). |
| El cambio de puerto no contaba como «cambio» (no había campo); en iOS cambiar host o puerto pone «Conectar» y, al salir, se conecta al nuevo sitio (`moved()` + reconexión). | Igual: host o puerto distintos de los que había al abrir cuentan como cambio, y salir conecta. |
| La nota bajo los interruptores: iOS habla del micrófono en uso; Android de su notificación («Dejar de escuchar»). | Se deja: cada una describe lo que hace su sistema. |

## Conexión

| Diferencia | Qué se hizo |
|---|---|
| Buscar por Bonjour solo el servidor emparejado (su «id» en el anuncio = «server» en /status); un servidor que contesta en la dirección conocida con otro id no es el nuestro; host o puerto cambiados a mano: solo ahí hasta que conteste (`exact`); al emparejar con un servidor sin HTTPS se olvida la autoridad y el puerto HTTPS que hubiera; el host que era una IP pasa a la nueva cuando Bonjour la encuentra. | Ya iguales (Mac.kt y Mac.swift). |
| Android prueba además `anyassistant.local` al final y recuerda el último nombre que contestó (`lastGood`); iOS no. | Se deja: no cambia el flujo y en Android muchos dispositivos no resuelven .local, por eso el orden es distinto. |
| «El servidor no responde: ¿está AnyAssistant en marcha y este dispositivo en la misma red?» y «Ese código no es correcto (o ha caducado).»: preguntas; el Mac (y iOS desde su commit «iPhone, iPad and watch errors as the Mac's») los dice como afirmaciones con qué hacer. | «El servidor no responde. Comprueba que AnyAssistant esté en marcha y que este dispositivo esté en la misma red.» y «El código no es correcto o ha caducado.» (en inglés «The server isn't responding. Make sure AnyAssistant is running and this device is on the same network.», «The code is incorrect or has expired.»). Los demás («Buscando el servidor…», «Hay que emparejarlo de nuevo.», «Permite la cámara en Ajustes para escanear el código.») ya eran afirmaciones. |
| Si el micrófono no arranca, iOS lo escribe en el registro del servidor («no microphone…»); Android callaba. | `Audio.start` dice si arrancó y `Link` lo informa igual. |

## Alarmas, temporizadores y avisos

| Diferencia | Qué se hizo |
|---|---|
| iOS 26: alarmas del sistema (AlarmKit); antes, notificaciones. Android: el despertador del sistema (`setAlarmClock`), sonando en el canal de alarmas, a pantalla completa sobre el bloqueo, con «Parar»; parado en el teléfono, el servidor para también (`stopRinging` → tap si la cara está en «alarm»). Títulos «Alarma», «Recordatorio», «Temporizador» + « · etiqueta». | Ya equivalentes, cada uno con lo suyo del sistema. |
| Respuestas y mensajes de otras habitaciones como notificación solo en segundo plano, solo del asistente y no parciales, con el nombre del asistente. | Ya igual. |

## Cámara

| Diferencia | Qué se hizo |
|---|---|
| Si la foto («lee esto») falla, iOS manda el último fotograma y, si no hay, lo escribe en el registro; Android no mandaba nada. | Guarda el último fotograma y lo usa si la foto falla; sin nada, lo informa en el registro como iOS. |
| Frontal, un fotograma por segundo despierto (960 px, calidad 0,7), sin espejo lo que va al servidor, foto a resolución completa; solo con «eyes» y la app delante; «muestra la cámara» en vivo bajo la cara. | Ya igual. |

## Escuchar en segundo plano, palabra de activación, aprender la voz

| Diferencia | Qué se hizo |
|---|---|
| Con la pantalla apagada sigue escuchando mientras no se cierre (iOS: modo de audio en segundo plano; Android: servicio en primer plano con su notificación y «Dejar de escuchar»); el interruptor «Seguir escuchando con la pantalla apagada» lo desactiva. | Ya equivalentes. |
| La palabra de activación, las preguntas del aprendizaje de voz («Aprende mi voz»: nombre y cinco frases), la confirmación («¿lo hago?») y los avisos («conviene volver a aprender tu voz») los decide el servidor y llegan como estados y textos; las dos apps los pintan por `FaceModel`/`FaceState` (mismo mapa de estados, mismos textos del `/config`). | Ya igual. |
| Un «tap» en la cara (parar de hablar o despertar), «Hablar con AnyAssistant» (Siri y Acción en iOS; atajo, ajuste rápido y gesto de asistente en Android) como un tap, o al conectar si aún no lo está. | Ya equivalentes. |
| Una llamada u otra app con el audio: iOS reinicia el audio cuando acaba la interrupción; Android no observa el foco de audio. | No se ha hecho: no hay dispositivo para comprobar qué hace cada fabricante con `AudioRecord` en modo comunicación durante una llamada; queda anotado. |

## Textos

Todos los textos de la app comparados con `apps/ios/Resources/{en,es}.lproj/Localizable.strings`:
iguales palabra por palabra salvo los propios de Android (la notificación «%s te escucha» / «Dejar de
escuchar», los canales de notificación, «Hablar» del atajo, «Atrás» del botón). Se quitan dos que no
se usaban («Código del servidor», «Vacío: lo encuentra solo…») y se añade «Conectando con %s…».

## Qué se ha comprobado y qué no

- `cd apps/android && ./gradlew -q assembleDebug` compila; la app no tiene pruebas unitarias.
- No hay dispositivo Android. En un emulador (Pixel 6, Android 16 arm64, creado para esto) con la
  app en español y un servidor de prueba en el Mac (uno que pide código y lo rechaza; otro sin
  código y sin WebSocket) se ha visto: la primera pantalla; «Otro servidor…» con Host y Puerto y el
  error en rojo bajo los campos cuando no responde; el código en seis casillas, que empareja con el
  sexto dígito y, rechazado, se vacía y muestra «El código no es correcto o ha caducado.» en lugar de
  la ayuda; abrir la app por `anyassistant://connect?…&name=Eva` muestra «Conectando con Eva…» con
  su rueda y, al fallar, el error bajo los servidores; emparejado sin código, la cara (ojos tristes,
  «Buscando el servidor…») con el botón «Ajustes»; los ajustes con «Servidor», Host y Puerto,
  «Conectar» y «Emparejar de nuevo»; «Emparejar de nuevo» abre la pantalla de conectar con la X que
  vuelve a la cara.
- No se ha podido probar en vivo con un servidor AnyAssistant real: la cara conectada y sus temas en
  marcha, la cámara, el audio, las alarmas, el escaneo del QR (el emulador no tiene cámara real) ni
  Bonjour (el emulador no ve la red local).
- iOS no se ha tocado: no se ha encontrado ningún fallo real en la referencia.
