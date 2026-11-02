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
