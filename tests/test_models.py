"""The pinned models (server/models.py): their registry, the checks and the downloads."""

import hashlib
import io
import json
import re

import pytest

import models


@pytest.fixture
def registry(tmp_path, monkeypatch):
    """A registry of its own, remembering checks in a temporary file, with a URL model «tiny»."""
    monkeypatch.setattr(models, "VERIFIED", tmp_path / "verified.json")
    monkeypatch.setattr(models, "_folders", {})
    data = b"the model's weights"
    tiny = models.Model(url="https://example.test/release/", files={"tiny.bin": hashlib.sha256(data).hexdigest()})
    monkeypatch.setattr(models, "MODELS", {**models.MODELS, "tiny": tiny})
    monkeypatch.setattr(models.paths, "CACHE", tmp_path / "cache")
    return {"data": data, "folder": tmp_path / "cache" / "models" / "tiny"}


def test_every_model_is_pinned():
    for name, model in models.MODELS.items():
        assert model.files, name
        assert bool(model.repo) != bool(model.url), f"{name}: a repo or a URL"
        if model.repo:
            assert re.fullmatch(r"[0-9a-f]{40}", model.revision), f"{name}: the commit's hash, not a branch"
        else:
            assert model.url.startswith("https://") and model.url.endswith("/"), name
        for file, sha in model.files.items():
            assert re.fullmatch(r"[0-9a-f]{64}", sha), f"{name}: {file}"


def test_the_plugins_ask_for_models_that_are_pinned():
    """The ids the plugins use by default are in the registry (a typo would silently unpin one)."""
    from plugins import stt_faster_whisper, stt_parakeet, stt_parakeet_onnx, voices

    for wanted in ("mlx-community/parakeet-tdt-0.6b-v3", stt_parakeet.FALLBACK, "mlx-community/whisper-base-mlx",
                   stt_parakeet_onnx.MODEL, *stt_faster_whisper.REPOS.values(), voices.MODEL[0], "kokoro"):
        assert wanted in models.MODELS, wanted
    assert stt_parakeet_onnx.MODEL == "nemo-parakeet-tdt-0.6b-v3"
    from plugins import tts_piper

    assert set(tts_piper.DEFAULTS.values()) <= set(tts_piper.VOICES)
    for voice in tts_piper.VOICES:  # each Piper voice: its model and its settings
        assert set(models.MODELS["piper-" + voice].files) == {f"{voice}.onnx", f"{voice}.onnx.json"}, voice
    assert voices.MODEL[1] in models.MODELS[voices.MODEL[0]].files
    assert {"base", "small", "large-v3-turbo"} <= set(stt_faster_whisper.REPOS)


def test_a_right_file_passes_and_is_remembered(registry, tmp_path):
    folder = tmp_path / "snapshot"
    folder.mkdir()
    (folder / "tiny.bin").write_bytes(registry["data"])
    models.verify("tiny", folder)
    remembered = json.loads(models.VERIFIED.read_text())
    assert str(folder / "tiny.bin") in remembered


def test_a_changed_file_is_an_error_that_names_it(registry, tmp_path):
    folder = tmp_path / "snapshot"
    folder.mkdir()
    (folder / "tiny.bin").write_bytes(b"something else")
    with pytest.raises(models.ModelError) as error:
        models.verify("tiny", folder)
    assert "tiny.bin" in str(error.value) and "tiny" in str(error.value)
    assert not models.VERIFIED.exists()  # nothing remembered as good


def test_a_missing_file_is_an_error(registry, tmp_path):
    folder = tmp_path / "snapshot"
    folder.mkdir()
    with pytest.raises(models.ModelError, match="tiny.bin is missing"):
        models.verify("tiny", folder)


def test_a_remembered_file_is_not_hashed_again_unless_it_changes(registry, tmp_path, monkeypatch):
    folder = tmp_path / "snapshot"
    folder.mkdir()
    path = folder / "tiny.bin"
    path.write_bytes(registry["data"])
    models.verify("tiny", folder)
    hashed = []
    real = models.sha256
    monkeypatch.setattr(models, "sha256", lambda p: hashed.append(p) or real(p))
    models.verify("tiny", folder)
    assert hashed == []
    path.write_bytes(b"something else")  # another size: hashed again, and wrong
    with pytest.raises(models.ModelError):
        models.verify("tiny", folder)
    assert hashed == [path]


def test_a_url_model_is_downloaded_once_and_checked(registry, monkeypatch):
    asked = []

    def urlopen(url):
        asked.append(url)
        return io.BytesIO(registry["data"])

    monkeypatch.setattr(models.urllib.request, "urlopen", urlopen)
    folder = models.fetch("tiny")
    assert folder == registry["folder"]
    assert (folder / "tiny.bin").read_bytes() == registry["data"]
    assert asked == ["https://example.test/release/tiny.bin"]
    assert models.fetch("tiny") == folder and len(asked) == 1  # there: not downloaded again
    assert models.pinned("tiny") == str(folder)


def test_a_wrong_download_is_not_kept(registry, monkeypatch):
    monkeypatch.setattr(models.urllib.request, "urlopen", lambda url: io.BytesIO(b"tampered"))
    with pytest.raises(models.ModelError, match="tiny.bin"):
        models.fetch("tiny")
    assert list(registry["folder"].iterdir()) == []  # neither the file nor its .part


def test_a_hub_model_comes_from_its_commit(registry, tmp_path, monkeypatch):
    snapshot = tmp_path / "hub" / "snapshots" / "f0c48c298fd835726c27956a5d617bad7115627e"
    snapshot.mkdir(parents=True)
    name = "Wespeaker/wespeaker-voxceleb-resnet34-LM"
    (snapshot / "voxceleb_resnet34_LM.onnx").write_bytes(b"onnx")
    calls = []

    def hf_hub_download(repo, file, revision):
        calls.append((repo, file, revision))
        return str(snapshot / file)

    monkeypatch.setitem(__import__("sys").modules, "huggingface_hub", type("M", (), {"hf_hub_download": hf_hub_download}))
    with pytest.raises(models.ModelError, match="voxceleb_resnet34_LM.onnx"):
        models.fetch(name)
    assert calls == [(name, "voxceleb_resnet34_LM.onnx", models.MODELS[name].revision)]


def test_an_unknown_model_is_given_back_unpinned(registry, caplog):
    assert models.folder("someone/other-model") is None
    assert models.pinned("someone/other-model") == "someone/other-model"
    assert "isn't pinned" in caplog.text
