"""The models the server downloads, pinned: for each one, where it comes from (a Hugging Face
repo and the exact commit, or a fixed URL), its files and their SHA-256.

A plugin asks for a model by the id it uses (the repo, a library's name for it): pinned(id)
gives it the folder with the files, downloaded if they weren't (huggingface_hub's cache,
~/.cache/huggingface, or the cache folder's «models» for plain URLs) and checked: a file whose
hash isn't the one here is an error that names it; it is never used. An id that isn't here (a
model chosen in «stt_model») is given back as it is: the library downloads it, as before, and
the log says it isn't pinned.

Once checked, a file is remembered (its size and date, in the cache's models/verified.json) so
it isn't hashed again at every start: hashing 4 GB takes seconds.

The voice detection (Silero VAD) and the openWakeWord models come inside their packages, pinned
by uv.lock: nothing to download. New hashes: `python server/models.py hashes <id>` prints the
cached files' (the ones already downloaded by huggingface_hub).

Plain Python (no numpy): bin/ scripts and the installer may import it.
"""

import hashlib
import json
import logging
import os
import sys
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path

import paths

log = logging.getLogger("models")


class ModelError(RuntimeError):
    """A file isn't the one expected (a changed or corrupt download)."""


@dataclass(frozen=True)
class Model:
    repo: str = ""  # Hugging Face repo
    revision: str = ""  # its commit
    url: str = ""  # or a fixed URL to download the files from (…/release-tag/), ending in /
    files: dict = field(default_factory=dict)  # file name → SHA-256


PIPER = "https://huggingface.co/rhasspy/piper-voices/resolve/b4e358ffcb232591bf73a540e70f7de528e4174a/"

MODELS = {
    # Speech recognition on the Mac (stt-parakeet, stt-mlx-whisper; the wake word's small Whisper)
    "mlx-community/parakeet-tdt-0.6b-v3": Model(
        "mlx-community/parakeet-tdt-0.6b-v3", "ed2b7e8c15f9aaa0b5772e2efb986255eaef7e15", files={
            "config.json": "f320f1292511f34ec47f513755fe20fd01dbfc09a925d42730e66059a6e1ef4c",
            "model.safetensors": "05e01c7f396c298cf7d23f61da7b504adeab698f0aaeafd9c82d198625464592",
        }),
    "mlx-community/whisper-large-v3-turbo": Model(
        "mlx-community/whisper-large-v3-turbo", "a4aaeec0636e6fef84abdcbe3544cb2bf7e9f6fb", files={
            "config.json": "b34fc29e4e11e0a25e812775dd67f4dd16fc2c8eb43d28ae25ff7d660ecb6379",
            "weights.safetensors": "951ed3fc1203e6a62467abb2144a96ce7eafca8fa77e3704fdb8635ff3e7f8a6",
        }),
    "mlx-community/whisper-base-mlx": Model(
        "mlx-community/whisper-base-mlx", "1e3e249fb8d01c655324bd6841b1deadffd6d04c", files={
            "config.json": "737220a6d958b3ad48e78f840fa991556266983c84ea2ca40e413389c62e4c2f",
            "weights.npz": "2f57d5f3ef473054c638961f90716f4ee415e8108de81313eccb2c5fd62eff0b",
        }),
    # Speech recognition on Windows and Linux (stt-parakeet-onnx: onnx-asr's name for it;
    # stt-faster-whisper: its sizes, and the wake word's «base»)
    "nemo-parakeet-tdt-0.6b-v3": Model(
        "istupakov/parakeet-tdt-0.6b-v3-onnx", "8f23f0c03c8761650bdb5b40aaf3e40d2c15f1ce", files={
            "config.json": "666903c76b9798caf2c210afd4f6cd60b08a8dbf9800ec8d7a3bc0d2148ac466",
            "encoder-model.int8.onnx": "6139d2fa7e1b086097b277c7149725edbab89cc7c7ae64b23c741be4055aff09",
            "decoder_joint-model.int8.onnx": "eea7483ee3d1a30375daedc8ed83e3960c91b098812127a0d99d1c8977667a70",
            "vocab.txt": "d58544679ea4bc6ac563d1f545eb7d474bd6cfa467f0a6e2c1dc1c7d37e3c35d",
        }),
    "Systran/faster-whisper-small": Model(
        "Systran/faster-whisper-small", "536b0662742c02347bc0e980a01041f333bce120", files={
            "config.json": "b55496ac7940a7ae47d2c01eab40edfd8701feec1229d9cce3b40014383fb828",
            "model.bin": "3e305921506d8872816023e4c273e75d2419fb89b24da97b4fe7bce14170d671",
            "tokenizer.json": "fb7b63191e9bb045082c79fd742a3106a12c99513ab30df4a0d47fa6cb6fd0ab",
            "vocabulary.txt": "34ce3fe1c5041027b3f8d42912270993f986dbc4bb34cf27f951e34a1e453913",
        }),
    "Systran/faster-whisper-base": Model(
        "Systran/faster-whisper-base", "ebe41f70d5b6dfa9166e2c581c45c9c0cfc57b66", files={
            "config.json": "56a6d8110d311f19c8f0471e562832c7527f146b567275bfca59fcf7c184da9a",
            "model.bin": "d01c3014881c9c6f3133c182f3d2887eb6ca1c789a7538c5c007196857a0a6a9",
            "tokenizer.json": "fb7b63191e9bb045082c79fd742a3106a12c99513ab30df4a0d47fa6cb6fd0ab",
            "vocabulary.txt": "34ce3fe1c5041027b3f8d42912270993f986dbc4bb34cf27f951e34a1e453913",
        }),
    "mobiuslabsgmbh/faster-whisper-large-v3-turbo": Model(
        "mobiuslabsgmbh/faster-whisper-large-v3-turbo", "0a363e9161cbc7ed1431c9597a8ceaf0c4f78fcf", files={
            "config.json": "b0253ea6c0d3bea6b1e19e91a02acfd3b53f4467362efcb5a3e6b16c9b3a9b7e",
            "preprocessor_config.json": "7ccc62c6f2765af1f3b46c00c9b5894426835a05021c8b9c01eecb6dfb542711",
            "model.bin": "e76620f83d5f5b69efd3d87e3dc180c1bd21df9fbebacfd4335e5e1efcc018da",
            "tokenizer.json": "297b13372ac43916285644fb9687add3cc62ee2a1adb60da3dc25cc94c1871fd",
            "vocabulary.json": "c69260f2ab26d659b7c398f9a2b2b48ed0df16c3b47d7326782fd9cba71690c1",
        }),
    # Voice prints (voices)
    "Wespeaker/wespeaker-voxceleb-resnet34-LM": Model(
        "Wespeaker/wespeaker-voxceleb-resnet34-LM", "f0c48c298fd835726c27956a5d617bad7115627e", files={
            "voxceleb_resnet34_LM.onnx": "7bb2f06e9df17cdf1ef14ee8a15ab08ed28e8d0ef5054ee135741560df2ec068",
        }),
    # The voice on Windows and Linux (tts-kokoro): a GitHub release
    "kokoro": Model(
        url="https://github.com/thewh1teagle/kokoro-onnx/releases/download/model-files-v1.0/", files={
            "kokoro-v1.0.int8.onnx": "6e742170d309016e5891a994e1ce1559c702a2ccd0075e67ef7157974f6406cb",
            "voices-v1.0.bin": "bca610b8308e8d99f32e6fe4197e7ec01679264efed0cac9140fe9c29f1fbf7d",
        }),
    # The light voice (tts-piper): each voice its own model, from rhasspy/piper-voices at a commit
    # («piper-<voice>»: downloaded the first time that voice speaks)
    "piper-es_ES-davefx-medium": Model(url=PIPER + "es/es_ES/davefx/medium/", files={
        "es_ES-davefx-medium.onnx": "6658b03b1a6c316ee4c265a9896abc1393353c2d9e1bca7d66c2c442e222a917",
        "es_ES-davefx-medium.onnx.json": "0e0dda87c732f6f38771ff274a6380d9252f327dca77aa2963d5fbdf9ec54842"}),
    "piper-es_ES-carlfm-x_low": Model(url=PIPER + "es/es_ES/carlfm/x_low/", files={
        "es_ES-carlfm-x_low.onnx": "d69677323a907cd4963f42b29c20a98b5d6bfa7f3e64df339915e4650c00d125",
        "es_ES-carlfm-x_low.onnx.json": "d9bdfa9ff01eb2bc9e62e7d2593939d1e4c4d8eb7cf75f972731539d12399966"}),
    "piper-es_MX-claude-high": Model(url=PIPER + "es/es_MX/claude/high/", files={
        "es_MX-claude-high.onnx": "3ef40a71ea63852cd8ab7e6fa7d2ecdcfa67a0b47c9c48e3f10e02ee02083ea0",
        "es_MX-claude-high.onnx.json": "1afc81f703c0e4cb3b4d7c0dca096b8b54a98806807f0170cf5eb5557723c12d"}),
    "piper-es_MX-ald-medium": Model(url=PIPER + "es/es_MX/ald/medium/", files={
        "es_MX-ald-medium.onnx": "019b3803293c93e34a206dd2e53a3889209a514e786fd7144f7b70196c579b63",
        "es_MX-ald-medium.onnx.json": "5a71498158e04afc8099bfd019c7e87c68eb9d042505a2b1a87e5c1ac2b1a61d"}),
    "piper-es_AR-daniela-high": Model(url=PIPER + "es/es_AR/daniela/high/", files={
        "es_AR-daniela-high.onnx": "7ceb1fc0dab349418c5b54a639ae9ee595212d7c9ea422220d8419163d5cc985",
        "es_AR-daniela-high.onnx.json": "aedbf69647e1d754c62ecf8e0366ca5f16af3e768e3c6b5329af6eb6bde3852b"}),
    "piper-en_US-lessac-medium": Model(url=PIPER + "en/en_US/lessac/medium/", files={
        "en_US-lessac-medium.onnx": "5efe09e69902187827af646e1a6e9d269dee769f9877d17b16b1b46eeaaf019f",
        "en_US-lessac-medium.onnx.json": "efe19c417bed055f2d69908248c6ba650fa135bc868b0e6abb3da181dab690a0"}),
    "piper-en_US-amy-medium": Model(url=PIPER + "en/en_US/amy/medium/", files={
        "en_US-amy-medium.onnx": "b3a6e47b57b8c7fbe6a0ce2518161a50f59a9cdd8a50835c02cb02bdd6206c18",
        "en_US-amy-medium.onnx.json": "95a23eb4d42909d38df73bb9ac7f45f597dbfcde2d1bf9526fdeaf5466977d77"}),
    "piper-en_US-ryan-medium": Model(url=PIPER + "en/en_US/ryan/medium/", files={
        "en_US-ryan-medium.onnx": "abf4c274862564ed647ba0d2c47f8ee7c9b717d27bdad9219100eb310db4047a",
        "en_US-ryan-medium.onnx.json": "44034c056cb15681b2ad494307c7f3f2e4499d1253c700c711fa0a4607ffe78d"}),
    "piper-en_GB-alba-medium": Model(url=PIPER + "en/en_GB/alba/medium/", files={
        "en_GB-alba-medium.onnx": "401369c4a81d09fdd86c32c5c864440811dbdcc66466cde2d64f7133a66ad03b",
        "en_GB-alba-medium.onnx.json": "aa965a2f02ecced632c2694e1fc72bbff6d65f265fab567ca945918c73dd89f4"}),
    "piper-en_GB-alan-medium": Model(url=PIPER + "en/en_GB/alan/medium/", files={
        "en_GB-alan-medium.onnx": "0a309668932205e762801f1efc2736cd4b0120329622adf62be09e56339d3330",
        "en_GB-alan-medium.onnx.json": "c0f0d124e5895c00e7c03b35dcc8287f319a6998a365b182deb5c8e752ee8c1e"}),
}

VERIFIED = paths.CACHE / "models" / "verified.json"  # what was already checked: path → [size, mtime]
CHUNK = 8 << 20


_folders: dict = {}  # id → its checked folder, once per run


def folder(model: str):
    """The folder with a model's pinned, checked files (downloaded if needed), or None when it
    isn't in MODELS (a warning: the library will download the latest, unchecked)."""
    if model not in MODELS:
        log.warning("model %s isn't pinned: not in server/models.py, its latest version is used unchecked", model)
        return None
    if model not in _folders:
        _folders[model] = fetch(model)
    return _folders[model]


def pinned(model: str) -> str:
    """Where a library loads a model from: its checked folder, or the id itself when it isn't pinned."""
    return str(folder(model) or model)


def fetch(name: str) -> Path:
    """The folder with a model's files, downloaded if needed and checked against their hashes."""
    model = MODELS[name]
    if model.url:
        folder = paths.CACHE / "models" / name
        folder.mkdir(parents=True, exist_ok=True)
        for file, sha in model.files.items():
            if not (folder / file).exists():
                _download(name, model.url + file, folder / file, sha)
    else:
        from huggingface_hub import hf_hub_download

        folder = None
        for file in model.files:
            found = Path(hf_hub_download(model.repo, file, revision=model.revision))
            folder = folder or found.parent  # the snapshot of that commit
    verify(name, folder)
    return folder


def verify(name: str, folder: Path):
    """Every file of a model is the one pinned, or ModelError says which isn't."""
    model = MODELS[name]
    known = _verified()
    changed = False
    for file, sha in model.files.items():
        path = folder / file
        try:
            stat = path.stat()
        except OSError:
            raise ModelError(f"{name}: {file} is missing from {folder}")
        mark = [stat.st_size, stat.st_mtime_ns]
        if known.get(str(path)) == mark:
            continue
        got = sha256(path)
        if got != sha:
            raise ModelError(f"{name}: {file} isn't the file pinned in server/models.py (SHA-256 {got}, "
                             f"expected {sha}): a changed or corrupt download, at {path}; delete it to download it again")
        log.info("model %s: %s checked", name, file)
        known[str(path)] = mark
        changed = True
    if changed:
        _remember(known)


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as f:
        while chunk := f.read(CHUNK):
            digest.update(chunk)
    return digest.hexdigest()


def _download(name: str, url: str, target: Path, sha: str):
    """A file from a fixed URL, checked before it takes its place."""
    log.info("model %s: downloading %s…", name, target.name)
    partial = target.with_name(target.name + ".part")
    try:
        with urllib.request.urlopen(url) as r, open(partial, "wb") as f:
            while chunk := r.read(CHUNK):
                f.write(chunk)
        got = sha256(partial)
        if got != sha:
            raise ModelError(f"{name}: {target.name} downloaded from {url} isn't the file pinned in server/models.py "
                             f"(SHA-256 {got}, expected {sha}): not used")
        partial.replace(target)
    finally:
        if partial.exists():
            partial.unlink()


def _verified() -> dict:
    try:
        with open(VERIFIED) as f:
            return json.load(f)
    except (OSError, ValueError):
        return {}


def _remember(known: dict):
    try:
        VERIFIED.parent.mkdir(parents=True, exist_ok=True)
        with open(VERIFIED, "w") as f:
            json.dump(known, f, indent=1)
    except OSError as e:
        log.warning("couldn't remember the checked models (%s): they'll be hashed again next time", e)


def hashes(name: str) -> dict:
    """The SHA-256 of a model's files as they are in huggingface_hub's cache (to pin a new one:
    download it first with the library, then `python server/models.py hashes <repo>`)."""
    from huggingface_hub import constants

    repo = MODELS[name].repo if name in MODELS else name
    folder = Path(constants.HF_HUB_CACHE) / ("models--" + repo.replace("/", "--"))
    revision = (folder / "refs" / "main").read_text().strip()
    snapshot = folder / "snapshots" / revision
    return {"repo": repo, "revision": revision,
            "files": {str(p.relative_to(snapshot)): sha256(p) for p in sorted(snapshot.rglob("*")) if p.is_file()}}


if __name__ == "__main__":
    if sys.argv[1:2] == ["hashes"] and sys.argv[2:]:
        print(json.dumps(hashes(sys.argv[2]), indent=2))
    else:
        print(__doc__)
