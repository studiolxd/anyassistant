"""Compila los puentes en Swift de los plugins (APIs de Apple sin acceso desde Python)."""

import logging
import subprocess
from pathlib import Path

log = logging.getLogger("swift")

BUILD = Path(__file__).resolve().parent.parent / ".build"


def compilar(fuente: Path, nombre: str) -> Path:
    """Compila `fuente` en .build/<nombre> si no existe o está desfasado."""
    binario = BUILD / nombre
    if binario.exists() and binario.stat().st_mtime >= fuente.stat().st_mtime:
        return binario
    log.info("compilando %s…", fuente.name)
    BUILD.mkdir(exist_ok=True)
    subprocess.run(["swiftc", "-O", str(fuente), "-o", str(binario)], check=True)
    return binario
