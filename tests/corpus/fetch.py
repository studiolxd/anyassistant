"""Downloads the corpus's selection into the cache (paths.CACHE/corpus) and builds the mixed cases.

Only what the manifest names is downloaded, never a whole dataset: a member of a tar by its byte
range, a row group of a Parquet file, a member of a zip (HTTP Range requests; the servers of
Hugging Face, OpenSLR and Zenodo accept them), or a tar.gz streamed until the last file wanted.
Every file is checked against the SHA-256 in the manifest before it is used; one that doesn't
match is an error that names it.

    bin/anyassistant corpus fetch [--common-voice FOLDER] [--only SOURCE…]

Common Voice comes from a mirror of the official release on Hugging Face (its licence, CC0,
allows it); --common-voice points at an official download instead (the folder with clips/ and
test.tsv), for when the mirror isn't there or you already have it.
"""

import hashlib
import io
import sys
import tarfile
import time
import urllib.error
import urllib.request
import zipfile
from pathlib import Path

import numpy as np

from corpus import (LEAD, TAIL, by_id, case_path, cases_folder, decode, manifest, mix, pad, raw_folder, reverberate,
                    segment, write_wav)

AGENT = "AnyAssistant-corpus/1 (+https://github.com/studiolxd)"
HF = "https://huggingface.co/datasets/{repo}/resolve/{revision}/{path}"
ATTEMPTS = 3


class FetchError(RuntimeError):
    pass


def log(message: str):
    print(message, flush=True)


# --- HTTP ---

def request(url: str, headers: dict | None = None, method: str = "GET"):
    last = None
    for attempt in range(ATTEMPTS):
        try:
            return urllib.request.urlopen(urllib.request.Request(url, headers={"User-Agent": AGENT, **(headers or {})},
                                                                 method=method), timeout=120)
        except (urllib.error.URLError, TimeoutError, ConnectionError) as e:
            last = e
            if isinstance(e, urllib.error.HTTPError) and e.code in (401, 403, 404):
                break
            time.sleep(2 * (attempt + 1))
    raise FetchError(f"couldn't download {url}: {last}")


def resolve(url: str) -> tuple[str, int]:
    """Where a download really is (Hugging Face sends to its CDN) and its size: resolved once,
    so each range request is one round trip."""
    with request(url, method="HEAD") as r:
        return r.url, int(r.headers["Content-Length"])


def read_range(url: str, offset: int, size: int) -> bytes:
    with request(url, {"Range": f"bytes={offset}-{offset + size - 1}"}) as r:
        if r.status != 206:
            raise FetchError(f"{url}: the server doesn't serve byte ranges (HTTP {r.status})")
        data = r.read()
    if len(data) != size:
        raise FetchError(f"{url}: got {len(data)} bytes of {size}")
    return data


class RemoteFile(io.RawIOBase):
    """A file on a server that serves byte ranges, read as a seekable file (for zipfile and
    pyarrow: only what they ask for is downloaded)."""

    def __init__(self, url: str):
        self.url, self.size = resolve(url)
        self.pos = 0
        self.requests = 0
        self.downloaded = 0

    def seekable(self):
        return True

    def readable(self):
        return True

    def tell(self):
        return self.pos

    def seek(self, offset, whence=0):
        self.pos = {0: offset, 1: self.pos + offset, 2: self.size + offset}[whence]
        return self.pos

    def read(self, n=-1):
        if n is None or n < 0:
            n = self.size - self.pos
        if n <= 0 or self.pos >= self.size:
            return b""
        data = read_range(self.url, self.pos, min(n, self.size - self.pos))
        self.pos += len(data)
        self.requests += 1
        self.downloaded += len(data)
        return data

    def readinto(self, buffer):
        data = self.read(len(buffer))
        buffer[:len(data)] = data
        return len(data)


def buffered(url: str, size: int = 1 << 20) -> io.BufferedReader:
    return io.BufferedReader(RemoteFile(url), size)


# --- Where each source's files are ---

def source_url(source: dict, archive: str | None = None) -> str:
    archive = archive or source.get("archive", "")
    if source.get("repo"):
        return HF.format(repo=source["repo"], revision=source["revision"], path=archive)
    return source["url"].format(archive=archive)


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def raw_path(case: dict) -> Path:
    return raw_folder() / case["source"] / Path(case["file"]).name


def have(case: dict) -> bool:
    return raw_path(case).exists()


def keep(case: dict, data: bytes, strict: bool = True) -> bool:
    """Writes a case's raw file once its hash is the manifest's; False (strict) or a warning
    otherwise."""
    got = sha256(data)
    if got != case["sha256"]:
        message = (f"{case['id']}: {case['file']} isn't the file in the manifest (SHA-256 {got}, "
                   f"expected {case['sha256']})")
        if strict:
            raise FetchError(message)
        log("  warning: " + message + "; used anyway (a local copy)")
    path = raw_path(case)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)
    return got == case["sha256"]


def fetch_tar_members(source: dict, cases: list[dict]):
    """Members of a plain tar by their byte offsets (one small request each)."""
    url, _ = resolve(source_url(source))
    for n, case in enumerate(cases, 1):
        if have(case):
            continue
        keep(case, read_range(url, case["offset"], case["size"]))
        if n % 25 == 0:
            log(f"  {n}/{len(cases)}")


def fetch_targz_stream(source: dict, archive: str, cases: list[dict]):
    """Streams a tar.gz and keeps the members wanted, stopping after the last one."""
    wanted = {Path(c["file"]).name: c for c in cases if not have(c)}
    if not wanted:
        return
    url = source_url(source, archive)
    log(f"  streaming {archive} until its {len(wanted)} files are found…")
    with request(url) as response:
        with tarfile.open(fileobj=response, mode="r|gz") as tar:
            for member in tar:
                case = wanted.get(Path(member.name).name)
                if case is None or not member.isfile():
                    continue
                keep(case, tar.extractfile(member).read())
                del wanted[Path(member.name).name]
                if not wanted:
                    break
    if wanted:
        raise FetchError(f"{archive}: not in it: {', '.join(wanted)}")


def fetch_parquet_rows(source: dict, cases: list[dict]):
    """Rows of a Parquet file on Hugging Face, by row group: only those groups are downloaded."""
    pending = [c for c in cases if not have(c)]
    if not pending:
        return
    try:
        import pyarrow.parquet as pq
    except ImportError:
        raise FetchError("pyarrow is needed to read the Parquet files (uv sync installs it)")
    url = source_url(source)
    remote = buffered(url)
    file = pq.ParquetFile(remote)
    groups = sorted({c["row_group"] for c in pending})
    for group in groups:
        log(f"  row group {group} of {Path(source['archive']).name}…")
        table = file.read_row_group(group, columns=["audio"])
        audio = table.column("audio")
        for case in pending:
            if case["row_group"] != group:
                continue
            row = audio[case["row"]].as_py()
            if Path(row.get("path") or "").name not in ("", Path(case["file"]).name):
                raise FetchError(f"{case['id']}: row {case['row']} of group {group} is {row.get('path')}, "
                                 f"not {case['file']}")
            keep(case, row["bytes"])


def fetch_zip_members(source: dict, archive: str, cases: list[dict]):
    """Members of a zip on a server that serves ranges: its directory, then each file."""
    pending = [c for c in cases if not have(c)]
    if not pending:
        return
    url = source_url(source, archive)
    with zipfile.ZipFile(buffered(url)) as z:
        for case in pending:
            keep(case, z.read(case["member"]))


def fetch_local_common_voice(folder: Path, cases: list[dict]) -> int:
    """Common Voice from an official download (its clips/ folder); how many files differed from
    the manifest's hashes (a warning each: they are the user's own copy)."""
    clips = folder / "clips" if (folder / "clips").is_dir() else folder
    differed = 0
    for case in cases:
        if have(case):
            continue
        path = clips / case["file"]
        if not path.exists():
            raise FetchError(f"{case['id']}: {path} isn't there")
        if not keep(case, path.read_bytes(), strict=False):
            differed += 1
    return differed


# --- The cases' audio ---

def build(found: dict, only: set | None = None):
    """Every case's WAV in the cache from the raw files: speech padded with silence, noise cut to
    its segment, mixed and reverberated ones made from both."""
    cases = by_id(found)
    clips: dict = {}

    def clip(case_id: str) -> np.ndarray:
        if case_id not in clips:
            case = cases[case_id]
            audio = decode(raw_path(case).read_bytes(), case["file"])
            if case["kind"] == "noise":
                audio = segment(audio, case.get("start", 0.0), case["seconds"])
            clips[case_id] = audio
        return clips[case_id]

    made = 0
    for case in found["cases"]:
        if only and case["source"] not in only and case.get("speech") not in cases:
            continue
        target = case_path(case["id"])
        if target.exists():
            continue
        kind = case["kind"]
        if kind == "speech":
            audio = pad(clip(case["id"]), LEAD, TAIL)
        elif kind == "noise":
            audio = clip(case["id"])
        elif kind == "rir":
            audio = clip(case["id"])
        elif kind == "mixed":
            audio = mix(clip(case["speech"]), clip(case["noise"]), case["snr"], cases[case["noise"]].get("start", 0.0))
        elif kind == "room":
            audio = pad(reverberate(clip(case["speech"]), clip(case["rir"])), LEAD, TAIL)
        else:
            raise FetchError(f"{case['id']}: unknown kind {kind}")
        write_wav(target, audio)
        made += 1
    return made


def fetch(found: dict | None = None, common_voice: Path | None = None, only: set | None = None) -> dict:
    """Downloads what is missing and builds the cases; a summary (files fetched, warnings)."""
    found = found or manifest()
    sources = found["sources"]
    raw_folder().mkdir(parents=True, exist_ok=True)
    cases_folder().mkdir(parents=True, exist_ok=True)
    summary = {"fetched": 0, "differed": 0}
    for name, source in sources.items():
        if only and name not in only:
            continue
        cases = [c for c in found["cases"] if c.get("source") == name]
        pending = [c for c in cases if not have(c)]
        if not pending:
            continue
        log(f"{source['title']}: {len(pending)} files…")
        kind = source["kind"]
        if name == "common_voice" and common_voice:
            summary["differed"] += fetch_local_common_voice(common_voice, cases)
        elif kind == "hf-tar":
            fetch_tar_members(source, cases)
        elif kind == "hf-targz":
            for archive in sorted({c["archive"] for c in pending}):
                fetch_targz_stream(source, archive, [c for c in cases if c["archive"] == archive])
        elif kind == "hf-parquet":
            fetch_parquet_rows(source, cases)
        elif kind == "zip":
            for archive in sorted({c.get("archive", source.get("archive", "")) for c in pending}):
                fetch_zip_members(source, archive, [c for c in cases if c.get("archive", source.get("archive", "")) == archive])
        else:
            raise FetchError(f"{name}: unknown source kind {kind}")
        summary["fetched"] += len(pending)
    log("building the cases…")
    summary["built"] = build(found, only)
    return summary


def check(found: dict | None = None) -> list[str]:
    """Which raw files in the cache don't match the manifest (none: all good or not there yet)."""
    found = found or manifest()
    wrong = []
    for case in found["cases"]:
        if "sha256" in case and have(case) and sha256(raw_path(case).read_bytes()) != case["sha256"]:
            wrong.append(case["id"])
    return wrong


def main(argv: list[str]) -> int:
    common_voice = None
    only = set()
    args = list(argv)
    while args:
        arg = args.pop(0)
        if arg == "--common-voice" and args:
            common_voice = Path(args.pop(0)).expanduser()
        elif arg == "--only" and args:
            only.add(args.pop(0))
        elif arg == "--check":
            wrong = check()
            print("every file matches" if not wrong else "wrong: " + ", ".join(wrong))
            return 1 if wrong else 0
        else:
            print(__doc__)
            return 2
    try:
        summary = fetch(common_voice=common_voice, only=only or None)
    except FetchError as e:
        print(f"error: {e}", file=sys.stderr)
        return 1
    print(f"done: {summary['fetched']} files fetched, {summary['built']} cases built, in {cases_folder()}"
          + (f"; {summary['differed']} local files differed from the manifest" if summary["differed"] else ""))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
