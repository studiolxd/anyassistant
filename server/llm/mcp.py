"""Qué servidores MCP puede usar Jarvis con Claude: solo los que diga mcp.json.

    {
      "permitidos": {
        "claude.ai Google Drive": ["search_files", "read_file_content"],
        "plugin:runpod:runpod": "todo"
      },
      "mcpServers": { "mi-servidor": { "command": "...", "args": [] } }
    }

- "permitidos": servidores ya autenticados en Claude Code (conectores de
  claude.ai y plugins), con el nombre que muestra `claude mcp list`; "todo" o
  la lista de herramientas que puede usar (las demás de ese servidor las ve,
  pero si intenta usarlas se le deniegan).
- "mcpServers": servidores propios, en el formato de Claude Code; se permiten
  enteros.

Claude Code carga siempre todos los conectores de la cuenta, así que los que no
están permitidos se prohíben (--disallowedTools): así ni ve sus herramientas ni
gastan tokens (con todos cargados eran 535 herramientas y ~770.000 tokens por
mensaje).
"""

import json
import logging
import re
import subprocess
from pathlib import Path

log = logging.getLogger("llm")


def prefijo(servidor: str) -> str:
    """«claude.ai Google Drive» → «mcp__claude_ai_Google_Drive», como lo nombra Claude Code."""
    return "mcp__" + re.sub(r"[^A-Za-z0-9_-]", "_", servidor)


def servidores_instalados() -> list[str]:
    """Los nombres de `claude mcp list` (tarda unos segundos: comprueba cada uno)."""
    salida = subprocess.run(
        ["claude", "mcp", "list"], capture_output=True, text=True, timeout=120
    ).stdout
    nombres = []
    for linea in salida.splitlines():
        # «claude.ai Google Drive: https://… - ✔ Connected», «plugin:runpod:runpod: https://…»
        if ": " in linea and " - " in linea:
            nombres.append(linea.split(": ", 1)[0].strip())
    return nombres


def argumentos(ruta: Path, salida: Path) -> list[str]:
    """Los argumentos de `claude` para usar solo lo que permite `ruta`.

    Sin archivo, ningún MCP (ni ajustes de usuario: arranca en 0,2 s). Con él
    hacen falta los ajustes de usuario, o no carga ni los conectores de
    claude.ai. `salida` es donde se escribe el --mcp-config con los servidores
    propios.
    """
    if not ruta.exists():
        return ["--strict-mcp-config", "--setting-sources", ""]
    config = json.loads(ruta.read_text())
    permitidos = config.get("permitidos", {})
    propios = config.get("mcpServers", {})

    instalados = servidores_instalados()
    permitir, prohibir = [], []
    for servidor in instalados:
        if servidor in propios:
            continue
        if servidor not in permitidos:
            prohibir.append(prefijo(servidor))
        elif permitidos[servidor] == "todo":
            permitir.append(prefijo(servidor))
        else:
            permitir += [f"{prefijo(servidor)}__{h}" for h in permitidos[servidor]]
    for servidor in propios:
        permitir.append(prefijo(servidor))
    for servidor in permitidos.keys() - set(instalados):
        log.warning("mcp.json permite «%s», pero no está en `claude mcp list`", servidor)

    args = ["--setting-sources", "user"]
    if propios:
        salida.write_text(json.dumps({"mcpServers": propios}))
        args += ["--mcp-config", str(salida)]
    if permitir:
        args += ["--allowedTools", *permitir]
    if prohibir:
        args += ["--disallowedTools", *prohibir]
    log.info("MCP permitidos: %s", ", ".join(permitir) or "ninguno")
    return args
