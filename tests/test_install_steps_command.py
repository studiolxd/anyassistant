"""How the installer says to run AnyAssistant from a terminal (install_steps.command): «anyassistant
start» when this copy is in the PATH, else its whole path (it said «bin/anyassistant start», which
isn't found from the home folder)."""

import shutil
import sys
from pathlib import Path

import pytest

import install_steps
import paths

pytestmark = pytest.mark.skipif(sys.platform == "win32", reason="Windows: its app runs it, not a terminal")


def test_in_the_path_it_is_short(monkeypatch, tmp_path):
    program = tmp_path / "opt" / "AnyAssistant" / "bin"
    program.mkdir(parents=True)
    (program / "anyassistant").write_text("")
    link = tmp_path / "bin" / "anyassistant"
    link.parent.mkdir()
    link.symlink_to(program / "anyassistant")
    monkeypatch.setattr(paths, "BIN", program)
    monkeypatch.setattr(shutil, "which", lambda name: str(link))
    assert install_steps.command("start") == "anyassistant start"


def test_else_its_whole_path_from_home(monkeypatch):
    monkeypatch.setattr(paths, "BIN", Path.home() / ".local" / "opt" / "AnyAssistant" / "bin")
    monkeypatch.setattr(shutil, "which", lambda name: None)
    assert install_steps.command("pair") == "~/.local/opt/AnyAssistant/bin/anyassistant pair"
