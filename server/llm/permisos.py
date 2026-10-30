"""Qué puede usar Jarvis con Claude: MCP del proyecto y comandos, solo lo permitido.

- .mcp.json: servidores MCP, en el formato de Claude Code (scope de proyecto).
  Se autentican abriendo `claude` en la carpeta del proyecto y usando /mcp: así
  quedan solo para el proyecto, sin tocar los conectores de la cuenta.
- permisos.json:

    {
      "permitidos": {"holded": "todo", "otro": ["get_x", "list_y"]},
      "comandos": ["bin/gog"]
    }

  "permitidos": herramientas de cada servidor de .mcp.json ("todo" o una lista;
  las demás de ese servidor las ve, pero se le deniegan). Un servidor que no
  aparece se prohíbe entero.
  "comandos": programas (rutas relativas al proyecto) que puede ejecutar, y nada
  más: se le da la terminal de Claude Code limitada a ellos, y en el prompt la
  salida de `<comando> ayuda` para que sepa usarlos.

Claude se arranca solo con los servidores de .mcp.json (--strict-mcp-config, sin
los conectores de claude.ai ni los plugins) y sin sus herramientas propias
(Bash, Edit…) salvo esa terminal limitada.
"""

import json
import logging
import re
import subprocess
from dataclasses import dataclass, field
from pathlib import Path

log = logging.getLogger("llm")


@dataclass
class Permisos:
    argumentos: list[str] = field(default_factory=list)  # para `claude`
    instrucciones: str = ""  # para el prompt de sistema
    herramientas: bool = False  # si puede usar alguna (MCP o comando)


def prefijo(servidor: str) -> str:
    """«claude.ai Google Drive» → «mcp__claude_ai_Google_Drive», como lo nombra Claude Code."""
    return "mcp__" + re.sub(r"[^A-Za-z0-9_-]", "_", servidor)


def ayuda(comando: Path) -> str:
    try:
        salida = subprocess.run(
            [str(comando), "ayuda"], capture_output=True, text=True, timeout=30
        ).stdout
    except OSError as e:
        log.warning("no se puede ejecutar %s: %s", comando, e)
        return ""
    return salida.strip()


def cargar(raiz: Path, servidores: Path) -> Permisos:
    archivo = raiz / "permisos.json"
    config = json.loads(archivo.read_text()) if archivo.exists() else {}
    permitidos = config.get("permitidos", {})
    comandos = [raiz / c for c in config.get("comandos", [])]

    args = ["--strict-mcp-config", "--setting-sources", ""]
    permitir, prohibir = [], []

    if servidores.exists() and permitidos:
        nombres = json.loads(servidores.read_text()).get("mcpServers", {})
        args += ["--mcp-config", str(servidores)]
        for servidor in nombres:
            herramientas = permitidos.get(servidor)
            if herramientas is None:
                prohibir.append(prefijo(servidor))
            elif herramientas == "todo":
                permitir.append(prefijo(servidor))
            else:
                permitir += [f"{prefijo(servidor)}__{h}" for h in herramientas]
        for servidor in permitidos.keys() - nombres.keys():
            log.warning("permisos.json permite «%s», que no está en .mcp.json", servidor)

    instrucciones = ""
    if comandos:
        args += ["--tools", "Bash"]
        textos = []
        for comando in comandos:
            if not comando.exists():
                log.warning("permisos.json permite %s, que no existe", comando)
                continue
            permitir.append(f"Bash({comando}:*)")
            relativo = str(comando.relative_to(raiz))
            textos.append(ayuda(comando).replace(relativo, str(comando)))
        instrucciones = (
            "\nPuedes ejecutar en la terminal solo estos comandos, con su ruta completa, "
            "de uno en uno y sin tuberías ni redirecciones:\n\n" + "\n\n".join(textos)
        )
    else:
        args += ["--tools", ""]

    if permitir:
        args += ["--allowedTools", *permitir]
    if prohibir:
        args += ["--disallowedTools", *prohibir]
    log.info("permitido: %s", ", ".join(permitir) or "nada")
    return Permisos(args, instrucciones, bool(permitir))
