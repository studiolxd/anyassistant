# Temas y plugins de la comunidad

AnyAssistant puede instalar, desde la propia app, temas y plugins compartidos por otras personas.
Todos salen de un **catálogo público**: un repositorio de GitHub
(`studiolxd/anyassistant-community`) con un índice JSON y los archivos de cada paquete.
Esta guía explica el formato del índice y cómo publicar un paquete.

- El índice: `index.json` en la raíz del repositorio. Su esquema está en
  [`comunidad/index.schema.json`](comunidad/index.schema.json) y hay un ejemplo completo en
  [`comunidad/index.example.json`](comunidad/index.example.json).
- Los paquetes: una carpeta por tema en `themes/<id>/` y una por plugin en `plugins/<id>/`.
- El servidor lee el índice en la dirección de la opción `community_catalog` (por defecto,
  `https://raw.githubusercontent.com/studiolxd/anyassistant-community/main/index.json`).

## Dónde se ve en la app

- **Temas**: la ventana «Temas» de la app del Mac y de la app de Windows y Linux (la página
  `/themes`), al final, «De la comunidad»: cada tema con su captura, instalar, actualizar y quitar.
  El tema recién instalado se muestra al momento.
- **Plugins**: Ajustes → Plugins → «De la comunidad», en el Mac y en la administración web
  (`/admin`, la de Windows y Linux y cualquier navegador con código de administración).
- Lo instalado desde el catálogo queda apuntado en `community.json` (en la carpeta de datos), con
  su versión: así la app sabe qué hay instalado, cuándo hay una actualización, y qué puede quitar.
  Un tema o plugin tuyo que no venga del catálogo nunca se toca.

## Cómo se avisa de las actualizaciones

Las actualizaciones **se avisan, nunca se instalan solas**.

- Si hay algo instalado desde el catálogo, el servidor lee el catálogo **una vez al día** (y unos
  minutos después de arrancar) y apunta en `community.json` las versiones nuevas que encuentra.
  Cada versión nueva se avisa **una sola vez**: si mañana sigue pendiente, no se vuelve a avisar;
  si sale otra versión, sí.
- Las apps (Mac, Windows y Linux) muestran una **notificación** por cada versión nueva: «Hay una
  actualización de Bedside (1.1.0)», o «Hay actualizaciones de 2 temas y plugins» si hay varias.
  Mientras haya actualizaciones pendientes, su menú muestra «Actualizaciones de la comunidad (2)…».
- La notificación y el menú abren dónde instalarlas: para un tema, la ventana «Temas» en su
  pestaña «De la comunidad» (`/themes#community`); para un plugin (o si hay de los dos tipos),
  Ajustes → Plugins → «De la comunidad» (en la administración web, `/admin#community`).
- No se avisa de una actualización que necesita una versión más nueva de AnyAssistant.
- Por voz, no se avisa.

Para las apps: `GET /admin/community/updates` (solo el propietario) devuelve `updates` (las
pendientes: `kind`, `id`, `name`, `from`, `to`) y `notice`, el último aviso (`id`, un número que
sube con cada aviso, y sus `updates` aún pendientes). Cada app recuerda el último número que
mostró. Esta consulta no lee el catálogo: solo dice lo que encontró la última lectura.

## Qué hace el servidor al instalar

1. Descarga **todos** los archivos del paquete a una carpeta provisional (`.installing`, junto
   a la de destino).
2. Comprueba el **SHA-256** de cada archivo con el del índice. Si uno no coincide, o falta, o
   es demasiado grande (10 MB por archivo, 50 MB por paquete), **no se instala nada** y la
   carpeta provisional se borra.
3. Comprueba el paquete: un tema debe pasar la misma revisión que los temas propios (sus tres
   archivos, bloques conocidos, nada de JavaScript ni recursos externos); un plugin, tener un
   `plugin.json` válido y no declararse de seguridad (`security`) ni bloqueado (`locked`): eso
   es solo para los del sistema.
4. Mueve la carpeta entera a su sitio: los temas a la carpeta de temas del usuario (`themes_dir`;
   por defecto `themes` en la carpeta de datos), los plugins a la carpeta `plugins` de la carpeta
   de datos. Una actualización sustituye la carpeta completa (la anterior se aparta y se borra
   después): no quedan archivos de la versión vieja.
5. Nunca sustituye un tema o plugin **del sistema**: un paquete con el mismo id que uno de ellos
   (`eyes`, `orb`, `minimal`, `bedside`; `memory`, `pairing`, `admin`…) se rechaza. Tampoco uno
   con el id de un tema o plugin propio que no venga del catálogo.

Los plugins son código Python que se ejecuta en el servidor **con los permisos del usuario**.
Por eso, antes de instalar uno, la app avisa y pide confirmación expresa (el servidor también la
exige: `"confirm": true`), y el plugin **empieza desactivado**: hay que activarlo en Plugins, tras
reiniciar. Los temas son HTML y CSS que el servidor limpia (sin JavaScript, sin cargar nada de
fuera): menos riesgo, no piden confirmación.

Las capturas de los temas las descarga el servidor y las sirve él (`/admin/community/image`):
las páginas de la app no cargan nada de fuera.

## El formato del índice

```json
{
  "format": 1,
  "updated": "2026-11-02",
  "packages": [
    {
      "kind": "theme",
      "id": "aurora",
      "name": "Aurora",
      "author": "Ana García",
      "version": "1.0.0",
      "description": "Luces del norte que respiran con tu voz.",
      "homepage": "https://github.com/studiolxd/anyassistant-community/tree/main/themes/aurora",
      "screenshot": "https://raw.githubusercontent.com/studiolxd/anyassistant-community/main/themes/aurora/preview.png",
      "min_version": 280,
      "files": [
        {"path": "theme.json", "url": "https://raw.githubusercontent.com/…/themes/aurora/theme.json", "sha256": "9f86…"},
        {"path": "theme.html", "url": "…/theme.html", "sha256": "6030…"},
        {"path": "theme.css",  "url": "…/theme.css",  "sha256": "fd61…"}
      ]
    }
  ]
}
```

| Campo | | |
|---|---|---|
| `format` | obligatorio | El formato del índice: `1`. Un servidor rechaza entero un índice de formato mayor que el que entiende, así que un cambio incompatible es un número nuevo (y un índice aparte para las versiones antiguas). |
| `updated` | opcional | Fecha del último cambio, `AAAA-MM-DD`. Solo informativo. |
| `packages` | obligatorio | La lista de paquetes. |

Cada paquete:

| Campo | | |
|---|---|---|
| `kind` | obligatorio | `theme` o `plugin`. |
| `id` | obligatorio | El nombre de su carpeta al instalarse: minúsculas, números, `-` y `_` (31 caracteres como mucho). Único dentro de su tipo. Nunca el de un tema o plugin del sistema. |
| `name` | obligatorio | Cómo se muestra. |
| `author` | opcional | Quién lo hizo. |
| `version` | obligatorio | Una versión legible (`1.0.0`, `2.1`). Hay actualización cuando la del catálogo es mayor que la instalada (orden PEP 440; si no se pueden comparar, cuando es distinta). |
| `description` | opcional | Una frase. |
| `homepage` | opcional | Dónde leer más (su carpeta en el repositorio o su propia página). |
| `screenshot` | opcional, temas | Dirección `https://` de un PNG o JPEG (3 MB como mucho). |
| `min_version` | opcional | La versión más antigua de AnyAssistant con la que funciona: el número de su `VERSION` (`280-9e919ad` → `280`; la app lo muestra bajo el nombre del equipo en Ajustes y en `/admin`). Una copia en desarrollo (sin `VERSION`) acepta cualquiera. |
| `files` | obligatorio | Todos los archivos del paquete, cada uno con `path` (ruta relativa dentro de la carpeta, sin `..`), `url` (`https://`) y `sha256` (hexadecimal). Un tema necesita `theme.json`, `theme.html` y `theme.css`, y solo archivos de los tipos que admite un tema (CSS, imágenes, fuentes, sonidos, JSON); un plugin, `plugin.json` y `__init__.py`. |

Solo se admiten direcciones `https://` (en el índice y en los archivos). Para un archivo del
repositorio, la dirección «raw» de GitHub:
`https://raw.githubusercontent.com/<usuario>/<repo>/<rama>/<ruta>`.

## Publicar un paquete

Un paquete se añade **por pull request** al repositorio del catálogo. **Cada paquete se revisa
antes de aceptarlo**: se lee su código entero (un plugin se ejecuta en el equipo de quien lo
instala), se comprueba que un tema pasa la revisión del servidor, y que los SHA-256 del índice
corresponden a los archivos. Un cambio en un paquete ya publicado es otra pull request, con la
versión subida y los SHA-256 nuevos; así, quien lo tenga instalado ve «hay una actualización».

1. **Haz el tema o el plugin** como uno propio (README: «Themes», «Plugins») y pruébalo en tu
   AnyAssistant. Pon en `theme.json` o `plugin.json` su `name`, `author`, `version` y
   `description`. Un tema, mejor con `preview.png` (una captura de la ventana «Temas», o del
   dispositivo).
2. **Clona el repositorio del catálogo** y copia la carpeta a `themes/<id>/` o `plugins/<id>/`.
   El nombre de la carpeta es su `id`. Nada de archivos ocultos ni `__pycache__`.
3. **Genera su entrada** para el índice, con los SHA-256 de cada archivo:

   ```sh
   bin/anyassistant community entry themes/aurora \
       https://raw.githubusercontent.com/studiolxd/anyassistant-community/main/themes/aurora
   ```

   (o `python plugins/community/cli.py entry <carpeta> <dirección base>`: es Python sin
   dependencias). Pega el resultado en `packages` de `index.json`; si quieres, añade
   `homepage` y `min_version`. Para comprobar un archivo a mano: `shasum -a 256 <archivo>`.
4. **Comprueba el índice** con el esquema (por ejemplo, `check-jsonschema --schemafile
   index.schema.json index.json`) y, si tienes el proyecto, con sus pruebas:
   `community.parse_index` no debe devolver problemas.
5. **Abre la pull request** explicando qué hace el paquete, qué necesita (`needs` en
   `plugin.json`: paquetes de Python, sistema, programas) y, si es un plugin, qué permisos usa
   (archivos, red, programas que lanza). Se revisará antes de publicarse.

### Lo que se revisa

- Que el paquete hace lo que dice, y nada más: un plugin no lee ni envía datos que no necesite,
  no descarga código en tiempo de ejecución, no toca los ajustes ni los archivos del usuario sin
  motivo, y no se declara `security` ni `locked`.
- Que un tema no contiene JavaScript ni carga recursos externos (el servidor los quita igual,
  pero no se publica algo que los lleve).
- Que los `files` del índice son exactamente los de la carpeta, con sus SHA-256 correctos.
- Que el `id` no es el de un tema o plugin del sistema, ni el de otro paquete del catálogo.
- Que `min_version` es correcto si el paquete usa algo reciente del servidor.

## Para probar con un catálogo propio

La opción `community_catalog` admite otra dirección `https://` (un fork del catálogo, por
ejemplo). Mientras desarrollas, también `http://127.0.0.1:<puerto>/index.json`: un servidor local
(solo en el propio equipo se admite HTTP). Las pruebas del proyecto (`tests/test_community.py`)
usan uno así.
