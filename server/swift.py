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
    "fm-bridge": paths.PLUGINS / "llm-apple" / "apple_bridge.swift",
    "avspeech-bridge": paths.PLUGINS / "tts-avspeech" / "avspeech_bridge.swift",
}
# The oldest macOS each one runs on. Without it swiftc takes this Mac's own version, and a bridge
# built on macOS 27 wouldn't open on 14 to 26 (the voice and Apple's model, gone there).
MINIMUM = {"fm-bridge": "26.0", "avspeech-bridge": "14.0"}  # Apple's model: macOS 26; the app: 14


def command(source: Path, name: str, output: Path) -> list[str]:
    import platform

    arch = "arm64" if platform.machine() == "arm64" else "x86_64"
    return ["swiftc", "-O", "-target", f"{arch}-apple-macos{MINIMUM.get(name, '14.0')}", str(source), "-o", str(output)]


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
    done = subprocess.run(command(source, name, binary), capture_output=True, text=True)
    if done.returncode:
        raise RuntimeError(f"swiftc couldn't build {source.name}: {done.stderr.strip()[-500:]}")
    return binary


def prebuild():
    """Builds every bridge into native/, for the installer."""
    NATIVE.mkdir(exist_ok=True)
    for name, source in BRIDGES.items():
        print(f"building {name}…")
        subprocess.run(command(source, name, NATIVE / name), check=True)


if __name__ == "__main__":
    if sys.argv[1:] == ["prebuild"]:
        prebuild()
    else:
        print("python server/swift.py prebuild   builds the Swift bridges into native/ (for the installer)")
