"""Shared fixtures. The server's modules import each other from server/ (pythonpath)."""

import importlib.machinery
import importlib.util
import shutil
from pathlib import Path

import pytest

import i18n

ROOT = Path(__file__).resolve().parent.parent


@pytest.fixture(params=["en", "es"])
def lang(request):
    """Runs the test once per language and leaves English active afterwards."""
    yield i18n.use(request.param)
    i18n.use("en")


@pytest.fixture
def en():
    yield i18n.use("en")


@pytest.fixture
def es():
    yield i18n.use("es")
    i18n.use("en")


def load_script(name: str, root: Path = ROOT):
    """A bin/ script (no .py extension) as a module, to test its functions."""
    path = root / "bin" / name
    loader = importlib.machinery.SourceFileLoader(name.replace("-", "_"), str(path))
    spec = importlib.util.spec_from_loader(loader.name, loader)
    module = importlib.util.module_from_spec(spec)
    loader.exec_module(module)
    return module


@pytest.fixture
def project(tmp_path):
    """A throwaway copy of bin/ so scripts that write next to the project write here."""
    shutil.copytree(ROOT / "bin", tmp_path / "bin")
    (tmp_path / ".build").mkdir()
    return tmp_path


@pytest.fixture(autouse=True)
def isolated(tmp_path, monkeypatch):
    """Tests never touch the running Jarvis: its timers (they would ring on the tablet), settings,
    memory, paired devices, confirmations and camera image all go to a temporary folder.
    Jarvis's tools don't ask for a «yes» here (test_tools checks that they do)."""
    import eyes
    import memory
    import pairing
    import settings
    import tools
    from skills import timers

    data = tmp_path / "jarvis"
    data.mkdir()
    monkeypatch.setattr(timers, "PATH", data / "timers.json")
    monkeypatch.setattr(timers, "changed", lambda: None)
    monkeypatch.setattr(settings, "PATH", data / "settings.json")
    monkeypatch.setattr(memory, "PATH", data / "memory.json")
    monkeypatch.setattr(pairing, "FILE", data / "paired.json")
    monkeypatch.setattr(eyes, "FRAME", data / "eyes" / "now.jpg")
    monkeypatch.setattr(tools, "CONFIRM", data / "confirm")
    monkeypatch.setattr(tools, "confirmation_on", lambda: False)
