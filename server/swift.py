"""The plugins' Swift bridges (Apple APIs that Python cannot reach).

Installed, they come already built in the app (native/, by `python server/swift.py
prebuild`, which the installer runs): no compiler is needed on the user's Mac.
While developing, they are built the first time they are used, into the cache.
"""

import logging
import subprocess
import sys
from pathlib import Path

import paths

log = logging.getLogger("swift")

NATIVE = paths.APP / "native"  # built in advance, inside the app
BRIDGES = {  # name: source
    "fm-bridge": paths.APP / "server" / "llm" / "apple_bridge.swift",
    "avspeech-bridge": paths.APP / "server" / "tts" / "avspeech_bridge.swift",
}


def build(source: Path, name: str) -> Path:
    """The bridge's binary: the app's own if it has one; otherwise compiled into the cache
    (again only if the source changed)."""
    shipped = NATIVE / name
    if shipped.exists():
        return shipped
    binary = paths.CACHE / name
    if binary.exists() and binary.stat().st_mtime >= source.stat().st_mtime:
        return binary
    log.info("building %s…", source.name)
    paths.CACHE.mkdir(parents=True, exist_ok=True)
    subprocess.run(["swiftc", "-O", str(source), "-o", str(binary)], check=True)
    return binary


def prebuild():
    """Builds every bridge into native/, for the installer."""
    NATIVE.mkdir(exist_ok=True)
    for name, source in BRIDGES.items():
        print(f"building {name}…")
        subprocess.run(["swiftc", "-O", str(source), "-o", str(NATIVE / name)], check=True)


if __name__ == "__main__":
    if sys.argv[1:] == ["prebuild"]:
        prebuild()
    else:
        print("python server/swift.py prebuild   builds the Swift bridges into native/ (for the installer)")
