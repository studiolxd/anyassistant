"""bin/gog: Google under permissions.json's policy."""

import json
import subprocess
import sys

import pytest

from conftest import ROOT, load_script


def gog(project, policy):
    (project / "permissions.json").write_text(json.dumps({"commands": {"bin/gog": policy}}))
    return load_script("gog")


def run(project, *args):
    return subprocess.run([sys.executable, ROOT / "bin" / "gog", *args], capture_output=True, text=True)


def test_without_permissions_it_only_reads(project):
    module = load_script("gog")
    assert module.policy() == "read"
    options = module.options("read")
    assert "--readonly" in options and "--gmail-no-send" in options


def test_all_allows_everything(project):
    module = gog(project, "all")
    assert module.policy() == "all"
    assert "--readonly" not in module.options("all")
    assert "--enable-commands-exact" not in module.options("all")


def test_a_list_allows_only_those(project):
    module = gog(project, ["gmail.search", "calendar.create"])
    options = module.options(module.policy())
    assert options[options.index("--enable-commands-exact") + 1] == "gmail.search,calendar.create"
    assert "--readonly" not in options and "--gmail-no-send" in options


def test_always_its_own_client_and_never_prompting(project):
    for policy in ("read", "all"):
        options = gog(project, policy).options(policy)
        assert options[:5] == ["--client", "jarvis", "--account", "auto", "--no-input"]


@pytest.mark.parametrize("args", [
    ["--readonly=false", "gmail", "send"],
    ["--client", "other", "gmail", "search", "x"],
    ["--account=me@x.com", "gmail", "search"],
    ["gmail", "delete", "--force"],
    ["auth", "list"],
    ["logout"],
    ["config", "set", "x"],
])
def test_it_refuses_changing_its_options_or_session(project, args):
    gog(project, "all")
    result = run(project, *args)
    assert result.returncode != 0
    assert "doesn't allow" in result.stderr


def test_help_mentions_writing_only_when_allowed(project):
    gog(project, "read")
    assert "It can also write" not in run(project, "help").stdout
    gog(project, "all")
    assert "It can also write (all)" in run(project, "help").stdout
