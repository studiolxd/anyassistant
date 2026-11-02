# El servidor en Windows y Linux

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

## La app de Windows y Linux

Servidor y cliente, como la del Mac, hecha con Electron. Arranca el
servidor, tiene el menú de la bandeja, y su cara es la página que ya existe (`/`, los cuatro
temas), con micrófono, cámara y cancelación de eco de Chromium, iguales en los dos sistemas.
Lo que la app del Mac dibuja en SwiftUI (ajustes, dispositivos, emparejar con QR, correo,
voces) se hizo una vez como páginas web de administración (`/admin`, solo desde el propio
equipo), y valen para los dos y para un Linux sin pantalla. Descartados: Tauri (en Linux usa
WebKitGTK, con WebRTC flojo) y Compose Desktop (reutilizaría los temas de Android, pero
Java no tiene cancelación de eco).

## Cómo se hizo, por fases

Cada una se podía usar al acabar. Lo que queda está en `TODO.md` («Windows y Linux»).

- **1. Núcleo portable** (1 nov): rutas XDG e instalación con systemd en Linux;
  `zeroconf` y `keyring` fuera del Mac (dependencias con marcador de sistema en
  `plugin.json`); PyTorch solo CPU; la alarma sin `afplay`; reiniciar sin señales
  (`web.stop`); los motores por defecto, los que tenga cada equipo. Probado en Ubuntu 24.04
  (OrbStack). Los tests corren en GitHub Actions en Linux, Windows y macOS en cada subida
  (encontraron 5 fallos de Windows y del certificado HTTPS, arreglados).
- **2. Motores portables** (1 nov): `stt-parakeet-onnx` (Parakeet v3 int8, 0,1–0,3 s por
  frase en CPU; con el respaldo de Whisper si se va al inglés), `stt-faster-whisper` (CPU
  int8, o NVIDIA si tiene sus librerías), `tts-kokoro` (Dora en español, ~4× tiempo real),
  `wake-whisper` con faster-whisper fuera del Mac. Probado en Ubuntu: «¿Qué hora es?» por
  `/talk` → «Son las 4 y 48 de la tarde» con la voz de Kokoro.
- **3. Linux sin pantalla** (1 nov): `install.sh` y el servicio de systemd; la
  administración web en `/admin` (emparejar con QR, dispositivos, ajustes, plugins, voces,
  correo, administradores), en el idioma del servidor. Desde el propio equipo, o desde un
  navegador con un código de administración (`bin/anyassistant admin-code` por SSH, o la
  página): de un solo uso, 5 minutos, cookie con su hash en `admins.json`, revocable; una
  tablet emparejada para hablar no puede administrar.
- **4. La app de bandeja** (1 nov, `apps/desktop`, Electron 44): adopta el servidor que ya
  funcione (el servicio de systemd) o arranca el suyo con uv y lo vigila (si se cae, otra vez;
  tres veces en 5 minutos, «ha fallado»); lo para limpio (`/admin/stop`); «Mostrar a Eva» (la
  página, con micrófono y cámara solo para 127.0.0.1), «Emparejar un dispositivo…» y
  «Administrar…» (`/admin`); abrir al iniciar sesión (Windows, y `~/.config/autostart` en
  Linux). Probada en el Mac (arranca su servidor, carga la cara, al salir lo para).
- **5. Paquetes, sin firmar** (1 nov): el instalador de Windows (.exe, NSIS, para tu
  usuario), el AppImage y el .deb, con el programa y uv dentro (sin Node ni uv aparte), hechos
  en GitHub Actions («packages»: a mano, o una etiqueta v* hace una versión en Releases).
  **v0.1.0 publicada** (1 nov), con la app del Mac también (`AnyAssistant-0.1.0-mac.dmg`, Apple
  Silicon, firmada y notarizada). La siguiente: subir `version` en `apps/desktop/package.json`,
  `git tag v0.1.1 && git push origin v0.1.1`.
