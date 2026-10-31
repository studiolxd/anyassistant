"""Builds the plugins' Swift bridges (Apple APIs that Python cannot reach)."""

import logging
import subprocess
from pathlib import Path

import paths

log = logging.getLogger("swift")

BUILD = paths.CACHE


def build(source: Path, name: str) -> Path:
    """Compiles `source` into .build/<name> unless it exists and is up to date."""
    binary = BUILD / name
    if binary.exists() and binary.stat().st_mtime >= source.stat().st_mtime:
        return binary
    log.info("building %s…", source.name)
    BUILD.mkdir(exist_ok=True)
    subprocess.run(["swiftc", "-O", str(source), "-o", str(binary)], check=True)
    return binary
