"""bin/anyassistant corpus …: the audio corpus (docs/corpus.md).

    corpus fetch [--common-voice FOLDER] [--only SOURCE]   downloads the selection into the cache, builds the cases
    corpus fetch --check                                   checks the downloaded files' hashes
    corpus status                                          what is in the cache, what the manifest has
    corpus run [--limit N] [--engine NAME] [--silence S] [--json FILE]   measures, and compares with the baseline
    corpus baseline                                        measures everything and writes baseline.json
"""

import sys


def status() -> int:
    from corpus import cases_folder, manifest, missing

    found = manifest()
    kinds: dict = {}
    for case in found["cases"]:
        kinds[case["kind"]] = kinds.get(case["kind"], 0) + 1
    lost = missing(found)
    print(f"manifest: {len(found['cases'])} cases " + ", ".join(f"{n} {k}" for k, n in sorted(kinds.items())))
    for name, source in found["sources"].items():
        print(f"  {name}: {source['title']} — {source['license']}")
    print(f"cache: {cases_folder()}: " + ("complete" if not lost else f"{len(lost)} cases missing (corpus fetch)"))
    return 0


def main(argv: list[str]) -> int:
    command = argv[0] if argv else "status"
    if command == "fetch":
        from corpus.fetch import main as fetch_main

        return fetch_main(argv[1:])
    if command in ("run", "baseline"):
        from corpus.run import main as run_main

        return run_main(argv)
    if command == "status":
        return status()
    print(__doc__)
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
