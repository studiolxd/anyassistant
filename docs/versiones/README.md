# Las notas de cada versión

Un archivo por versión, `v0.2.0.md`, con lo que trae para quien la instala: es la descripción
de su release en GitHub (`.github/workflows/release.yml`) y lo que el aviso de actualización
enseña en las apps. `apps/release.sh v0.2.0` no publica sin él: si falta, lista los commits
desde la versión anterior, para escribirlo a partir de ellos.

En español, con las palabras de las apps, por lo que cambia para quien la usa (no por archivos):

```markdown
## Novedades
- **El Apple Watch** muestra la cara de Eyes y te escucha mientras lo miras.

## Arreglos
- «A las siete y cinco» ya son las 7:05.

## Descargas
- **Mac** (Apple Silicon): `AnyAssistant-0.2.0-mac.dmg`.
- **Windows**: `AnyAssistant-0.2.0-win-x64.exe` (sin firmar: «Más información» → «Ejecutar de todas formas» la primera vez).
- **Linux**: el `.AppImage` o el `.deb`; sin app: `curl -fsSL https://github.com/studiolxd/anyassistant/releases/latest/download/install.sh | sh`.
- **iPhone, iPad y Apple Watch**: TestFlight.
```

## La clave de las actualizaciones del Mac (Sparkle)

Las apps del Mac instaladas solo aceptan una versión nueva si su `.dmg` está firmado con esta
clave (su parte pública va dentro de la app: `SUPublicEDKey` en `apps/mac/build.sh`). Si se pierde,
las apps ya instaladas no podrán actualizarse solas: habría que reinstalarlas a mano con una clave
nueva.

- **Dónde está:** en el llavero de inicio de sesión de este Mac (`login.keychain-db`), como
  contraseña genérica con el servicio `https://sparkle-project.org` y la cuenta `ed25519`.
- **Copia de seguridad** (a un archivo, para guardarlo en un gestor de contraseñas, no en el repo):
  `apps/mac/.build/artifacts/sparkle/Sparkle/bin/generate_keys -x sparkle-private-key.txt`
- **En un Mac nuevo:** `apps/mac/.build/artifacts/sparkle/Sparkle/bin/generate_keys -f sparkle-private-key.txt`
  (tras un `swift build` en `apps/mac`, que baja las herramientas de Sparkle).

Junto a ella hacen falta, para publicar desde otro Mac, el certificado «Developer ID Application»
(con su clave privada: exportado desde Acceso a Llaveros como `.p12`) y el perfil de notarización
(`xcrun notarytool store-credentials anyassistant`).
