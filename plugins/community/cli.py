"""For whoever publishes a theme or a plugin in the community catalog: its entry for the index,
with every file's path, address and SHA-256 (docs/comunidad.md). Plain Python, nothing else.

    bin/anyassistant community entry <folder> <base-url>
    python plugins/community/cli.py entry themes/aurora https://raw.githubusercontent.com/you/repo/main/themes/aurora

The folder's name is the package's id; theme.json or plugin.json gives its name, author, version
and description (and locales/<language>.json, the description in other languages); a theme's preview.png is its screenshot. Hidden files and __pycache__ are left out.
"""

import hashlib
import json
import sys
from pathlib import Path


def entry(folder: Path, base_url: str) -> dict:
    folder = Path(folder)
    kind = "theme" if (folder / "theme.json").exists() else "plugin"
    manifest = json.loads((folder / ("theme.json" if kind == "theme" else "plugin.json")).read_text())
    base_url = base_url.rstrip("/") + "/"
    files = []
    for file in sorted(p for p in folder.rglob("*") if p.is_file()):
        relative = file.relative_to(folder).as_posix()
        if any(part.startswith(".") or part == "__pycache__" for part in relative.split("/")):
            continue
        files.append({"path": relative, "url": base_url + relative,
                      "sha256": hashlib.sha256(file.read_bytes()).hexdigest()})
    made = {"kind": kind, "id": folder.name, "name": manifest.get("name", folder.name),
            "author": manifest.get("author", ""), "version": str(manifest.get("version", "1")),
            "description": manifest.get("description", "")}
    # Its description in other languages, from its locales (a theme's {"theme": {"description"}},
    # a plugin's {"plugins": {id: [name, description]}}): the catalog shows it in yours.
    descriptions = {}
    for locale in sorted((folder / "locales").glob("*.json")):
        try:
            texts = json.loads(locale.read_text())
            found = (texts["theme"]["description"] if kind == "theme" else texts["plugins"][folder.name][1])
        except (ValueError, KeyError, IndexError, TypeError):
            continue
        if isinstance(found, str) and found and found != made["description"]:
            descriptions[locale.stem] = found
    if descriptions:
        made["descriptions"] = descriptions
    if kind == "theme" and (folder / "preview.png").exists():
        made["screenshot"] = base_url + "preview.png"
    made["files"] = files
    return made


if __name__ == "__main__":
    if sys.argv[1:2] == ["entry"] and len(sys.argv) == 4:
        print(json.dumps(entry(Path(sys.argv[2]), sys.argv[3]), ensure_ascii=False, indent=2))
        sys.exit(0)
    print(__doc__.split("\n\n")[1])
    sys.exit(2)
