"""The plugin «llm-codex»: `codex app-server` (a fake one, tests/fake_codex.py) answering in pieces,
keeping the conversation, seeing, and asking for your «yes» through the plugin «confirmation»."""

import asyncio
import base64
import json
import os
import stat
import sys

import pytest

import i18n
import kernel
import paths
from conftest import ROOT
from llm import Unavailable

codex = kernel.load("llm-codex")
store = kernel.load("confirmation").store

pytestmark = pytest.mark.skipif(sys.platform == "win32", reason="the fake CLI is a script with #!")


@pytest.fixture
def fake(tmp_path, monkeypatch):
    """`codex` is the fake one; what it receives, in the returned function."""
    folder = tmp_path / "fake-bin"
    folder.mkdir()
    script = folder / "codex"
    script.write_text(f"#!{sys.executable}\n" + (ROOT / "tests" / "fake_codex.py").read_text())
    script.chmod(script.stat().st_mode | stat.S_IEXEC)
    log = tmp_path / "codex.log"
    monkeypatch.setenv("PATH", f"{folder}{os.pathsep}{os.environ['PATH']}")
    monkeypatch.setenv("FAKE_CODEX_LOG", str(log))
    monkeypatch.setattr(codex, "EMPTY", tmp_path / "codex-empty")
    monkeypatch.setattr(codex, "FILLER_AFTER", 0.2)

    def received():
        return [json.loads(line) for line in log.read_text().splitlines()] if log.exists() else []
    return received


def talk(*said, image=None, between=None):
    """What Codex answered to each sentence, in pieces."""
    async def run():
        model = codex.Codex()
        model.device = "ipad"
        heard = []
        try:
            for sentence in said:
                if sentence is None:
                    await model.new()
                    continue
                heard.append([piece async for piece in model.answer(sentence, image)])
                if between:
                    between()
        finally:
            await model.close()
        return heard
    return asyncio.run(run())


def test_it_answers_in_pieces_and_keeps_the_conversation(fake, es):
    heard = talk("hola", "otra vez", None, "hola de nuevo")
    assert heard == [["Hola", ", ¿qué tal?"]] * 3
    sent = fake()
    turns = [m["params"] for m in sent if m.get("method") == "turn/start"]
    assert [t["threadId"] for t in turns] == ["thread-1", "thread-1", "thread-2"]  # new() starts another
    assert turns[0]["input"][0]["text"].startswith("<now>") and turns[0]["input"][0]["text"].endswith("hola")
    thread = next(m["params"] for m in sent if m.get("method") == "thread/start")
    assert thread["sandbox"] == "read-only" and thread["approvalPolicy"] == "on-request" and thread["ephemeral"]
    assert thread["cwd"] == str(codex.EMPTY) and "Always reply in" in thread["baseInstructions"]
    assert len([m for m in sent if "argv" in m]) == 1  # one process for every conversation


def test_its_shell_files_and_extras_are_off_and_jarvis_tools_are_on(fake, es):
    talk("hola")
    argv = next(m["argv"] for m in fake() if "argv" in m)
    off = {argv[i + 1] for i, a in enumerate(argv) if a == "--disable"}
    assert {"shell_tool", "unified_exec", "view_image", "computer_use", "browser_use", "plugins", "apps"} <= off
    assert "code_mode_host" not in off  # Codex calls MCP tools through it
    assert not any(a.startswith("mcp_servers.anyassistant") for a in argv)  # permissions.json doesn't allow it

    paths.PERMISSIONS.write_text('{"allowed": {"anyassistant": ["get_status", "set_timer"]}}')
    arguments = codex.Codex()
    arguments.device = "ipad"
    found = arguments._arguments()
    assert 'mcp_servers.anyassistant.url="http://127.0.0.1:8080/mcp?device=ipad"' in found
    assert 'mcp_servers.anyassistant.enabled_tools=["get_status", "set_timer"]' in found


def test_the_image_goes_with_the_question(fake, es):
    talk("¿qué ves?", image=b"\xff\xd8jpeg")
    turn = next(m["params"] for m in fake() if m.get("method") == "turn/start")
    assert turn["input"][1] == {"type": "image", "url": "data:image/jpeg;base64," + base64.b64encode(b"\xff\xd8jpeg").decode()}


def test_what_changes_something_waits_for_your_yes_to_that_call(fake, es):
    paths.PERMISSIONS.write_text("{}")  # «confirm» on
    assert talk("manda una nota") == [["¿La mando?"]]  # refused: Codex asks you
    pending = store.pending()
    assert pending["action"] == 'family: send_note {"text": "hola"}'
    assert pending["signature"] == store.signature("mcp__family__send_note", {"text": "hola"})  # as Claude's hook
    store.answer(True)
    assert talk("manda una nota") == [["Hecho."]]
    assert talk("manda una nota") == [["¿La mando?"]]  # used up
    replies = [m["result"]["action"] for m in fake() if m.get("id") == 900 and "result" in m]
    assert replies == ["decline", "accept", "decline"]


def test_reads_go_through(fake, es):
    paths.PERMISSIONS.write_text("{}")
    assert talk("mira la lista") == [["Hecho."]]
    assert store.pending() is None


def test_without_confirmation_nothing_asks(fake, es):
    """permissions.json «confirm»: false (as in these tests by default)."""
    assert talk("manda una nota") == [["Hecho."]]


def test_a_slow_tool_gets_a_filler_and_is_reported(fake, es):
    seen = []

    async def run():
        model = codex.Codex()
        model.on_tool = lambda name, arguments=None: seen.append(name)
        try:
            return "".join([piece async for piece in model.answer("algo lento")])
        finally:
            await model.close()
    said = asyncio.run(run())
    assert any(said.startswith(w) for w in i18n.L.list("speech.wait")) and said.endswith("Soleado.")
    assert seen == ["mcp__anyassistant__get_weather"]


@pytest.mark.parametrize("sentence, key", [
    ("sin sesión", "speech.llm_signed_out"),
    ("sin límite", "speech.llm_limit"),
    ("se muere", "speech.llm_cut"),
])
def test_failures_are_unavailable(fake, es, sentence, key):
    with pytest.raises(Unavailable) as found:
        talk(sentence)
    assert found.value.sentence == i18n.L(key, name="Codex", command="codex login")


def test_signed_out_it_doesnt_wait_for_the_retries(fake, es):
    import time

    start = time.time()
    with pytest.raises(Unavailable):
        talk("sin sesión")
    assert time.time() - start < 4  # the fake retries for 5 s
    assert any(m.get("method") == "turn/interrupt" for m in fake())


def test_after_dying_the_next_question_starts_another(fake, es):
    async def run():
        model = codex.Codex()
        try:
            with pytest.raises(Unavailable):
                [piece async for piece in model.answer("se muere")]
            return [piece async for piece in model.answer("hola")]
        finally:
            await model.close()
    assert asyncio.run(run()) == ["Hola", ", ¿qué tal?"]


def test_ready(fake, monkeypatch):
    assert codex.Codex.ready() == "Codex isn't signed in"
    monkeypatch.setenv("FAKE_CODEX_SIGNED_IN", "1")
    assert codex.Codex.ready() is None
    monkeypatch.setenv("PATH", "/nonexistent")
    assert codex.Codex.ready() == "Codex isn't installed"


def test_complete_is_a_one_off_without_your_settings(fake):
    assert asyncio.run(codex.Codex().complete("hola")) == "Dijiste: hola"
    argv = next(m["argv"] for m in fake() if "argv" in m)
    assert argv[0] == "exec" and "--ignore-user-config" in argv and "--ephemeral" in argv
    assert not list(codex.EMPTY.glob("complete-*"))  # its answer file, removed


def test_trouble():
    assert codex.trouble({"codexErrorInfo": "unauthorized"}) == "signed_out"
    assert codex.trouble({"codexErrorInfo": {"responseStreamDisconnected": {"httpStatusCode": 401}}}) == "signed_out"
    assert codex.trouble({"codexErrorInfo": "usageLimitExceeded"}) == "limit"
    assert codex.trouble({"codexErrorInfo": {"httpConnectionFailed": {"httpStatusCode": None}}}) == "offline"
    assert codex.trouble({"codexErrorInfo": "internalServerError"}) == "failed"
    assert codex.trouble(None) == "failed"
