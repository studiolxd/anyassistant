"""Qué servidores MCP puede usar Jarvis con Claude: los del proyecto, y solo lo permitido.

- .mcp.json: los servidores, en el formato de Claude Code (scope de proyecto).
  Se autentican abriendo `claude` en la carpeta del proyecto y usando /mcp: así
  quedan solo para el proyecto, sin tocar los conectores de la cuenta.
- permisos.json: qué herramientas de cada uno puede usar Jarvis.

    {"permitidos": {"gmail": ["search_threads", "get_thread"], "holded": "todo"}}

Claude se arranca solo con los servidores de .mcp.json (--strict-mcp-config, sin
los conectores de claude.ai ni los plugins). Los que no aparecen en permisos.json
se prohíben enteros; de los que sí, solo se permiten las herramientas listadas
(ve las demás, pero se le deniegan).
"""

import json
import logging
import re
from pathlib import Path

log = logging.getLogger("llm")

NINGUNO = ["--strict-mcp-config", "--setting-sources", ""]


def prefijo(servidor: str) -> str:
    """«claude.ai Google Drive» → «mcp__claude_ai_Google_Drive», como lo nombra Claude Code."""
    return "mcp__" + re.sub(r"[^A-Za-z0-9_-]", "_", servidor)


def argumentos(servidores: Path, permisos: Path) -> list[str]:
    """Los argumentos de `claude` para usar solo lo permitido; sin archivos, ningún MCP."""
    if not servidores.exists() or not permisos.exists():
        return NINGUNO
    nombres = json.loads(servidores.read_text()).get("mcpServers", {})
    permitidos = json.loads(permisos.read_text()).get("permitidos", {})

    permitir, prohibir = [], []
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

    args = [*NINGUNO, "--mcp-config", str(servidores)]
    if permitir:
        args += ["--allowedTools", *permitir]
    if prohibir:
        args += ["--disallowedTools", *prohibir]
    log.info("MCP permitidos: %s", ", ".join(permitir) or "ninguno")
    return args
