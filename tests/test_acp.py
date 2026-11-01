"""The plugins «llm-gemini» and «llm-opencode» (server/llm/acp.py): a fake ACP agent
(tests/fake_acp.py) answering in pieces, keeping the conversation, seeing, and waiting for your
«yes» (the plugin «confirmation») before an MCP tool that changes something."""

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

gemini = kernel.load("llm-gemini")
opencode = kernel.load("llm-opencode")
store = kernel.load("confirmation").store
PLUGINS = {"gemini": gemini.Gemini, "opencode": opencode.OpenCode}

pytestmark = pytest.mark.skipif(sys.platform == "win32", reason="the fake CLI is a script with #!")


def fake(flavor, tmp_path, monkeypatch):
    """The plugin's class, run against the fake agent; what the agent received, in .received()."""
    folder = tmp_path / "fake-bin"
    folder.mkdir()
    script = folder / flavor
    script.write_text(f"#!{sys.executable}\n" + (ROOT / "tests" / "fake_acp.py").read_text())
    script.chmod(script.stat().st_mode | stat.S_IEXEC)
    log = tmp_path / "acp.log"
    monkeypatch.setenv("PATH", f"{folder}{os.pathsep}{os.environ['PATH']}")
    monkeypatch.setenv("FAKE_ACP_LOG", str(log))
    monkeypatch.setattr(opencode, "CONFIG", tmp_path / "no-config")  # not your OpenCode's servers
    cls = PLUGINS[flavor]
    monkeypatch.setattr(cls, "folder", tmp_path / f"{flavor}-empty")
    monkeypatch.setattr(sys.modules["llm.acp"], "FILLER_AFTER", 0.2)

    def received():
        return [json.loads(line) for line in log.read_text().splitlines()] if log.exists() else []
    monkeypatch.setattr(cls, "received", staticmethod(received), raising=False)
    return cls


@pytest.fixture(params=["gemini", "opencode"])
def agent(request, tmp_path, monkeypatch):
    return fake(request.param, tmp_path, monkeypatch)


@pytest.fixture
def gemini_agent(tmp_path, monkeypatch):
    return fake("gemini", tmp_path, monkeypatch)


@pytest.fixture
def opencode_agent(tmp_path, monkeypatch):
    return fake("opencode", tmp_path, monkeypatch)


def talk(cls, *said, image=None, answer=None):
    """What it answered to each sentence (None: a new conversation); `answer`: your answer when
    it asks («¿Lo hago?»)."""
    async def run():
        model = cls()
        model.device = "ipad"
        heard = []
        try:
            for sentence in said:
                if sentence is None:
                    await model.new()
                    continue
                pieces = []
                async for piece in model.answer(sentence, image):
                    pieces.append(piece)
                    if answer is not None and store.pending():
                        store.answer(answer)
                heard.append("".join(pieces).strip())
        finally:
            await model.close()
        return heard
    return asyncio.run(run())


def prompts(cls):
    return [m["params"] for m in cls.received() if m.get("method") == "session/prompt"]


def test_it_answers_in_pieces_and_keeps_the_conversation(agent, es):
    assert talk(agent, "hola", "otra vez", None, "hola de nuevo") == ["Hola, ¿qué tal?"] * 3
    asked = prompts(agent)
    assert [p["sessionId"] for p in asked] == ["session-1", "session-1", "session-2"]  # new(): another
    first, second = asked[0]["prompt"][0]["text"], asked[1]["prompt"][0]["text"]
    assert "<now>" in first and first.endswith("hola") and second.startswith("<now>")
    if agent is opencode.OpenCode:  # its instructions, with each conversation's first message
        assert "Always reply in" in first and "Always reply in" not in second
    else:  # Gemini: in its system prompt
        assert "Always reply in" not in first
        assert any("Always reply in" in m.get("system", "") for m in agent.received())
    new = next(m["params"] for m in agent.received() if m.get("method") == "session/new")
    assert new["cwd"] == str(agent.folder)
    assert len([m for m in agent.received() if "argv" in m]) == 1  # one process for every conversation


def test_the_image_goes_with_the_question(agent, es):
    talk(agent, "¿qué ves?", image=b"\xff\xd8jpeg")
    assert prompts(agent)[0]["prompt"][1] == {"type": "image", "mimeType": "image/jpeg",
                                               "data": base64.b64encode(b"\xff\xd8jpeg").decode()}


def test_what_changes_something_waits_for_your_yes(agent, es):
    paths.PERMISSIONS.write_text("{}")  # «confirm» on
    heard = talk(agent, "manda una nota", answer=True)
    assert heard[0].startswith(f"{agent.NAME} quiere hacer esto: family: send note") and heard[0].endswith("Hecho.")
    replies = [m["result"]["outcome"] for m in agent.received() if m.get("id", 0) > 900 and "result" in m]
    assert replies == [{"outcome": "selected", "optionId": "once"}]  # once, not «always»
    assert store.pending() is None


def test_anything_but_yes_refuses_it(agent, es):
    paths.PERMISSIONS.write_text("{}")
    heard = talk(agent, "manda una nota", answer=False)
    assert "¿Lo hago?" in heard[0] and heard[0].endswith("Vale, no.")
    replies = [m["result"]["outcome"] for m in agent.received() if m.get("id", 0) > 900 and "result" in m]
    assert replies == [{"outcome": "selected", "optionId": "reject"}]


def test_reads_go_through(agent, es):
    paths.PERMISSIONS.write_text("{}")
    assert talk(agent, "mira la lista") == ["Hecho."]
    assert store.pending() is None


def test_without_confirmation_nothing_asks(agent, es):
    """permissions.json «confirm»: false (as in these tests by default)."""
    assert talk(agent, "manda una nota") == ["Hecho."]


def test_its_own_tools_are_refused(agent, es):
    with pytest.raises(Unavailable) as found:  # OpenCode then ends its turn, with nothing said
        talk(agent, "lee el fichero")
    assert found.value.sentence == i18n.L("speech.llm_failed")
    replies = [m["result"]["outcome"] for m in agent.received() if m.get("id", 0) > 900 and "result" in m]
    assert replies == [{"outcome": "selected", "optionId": "reject"}]


def test_a_slow_tool_gets_a_filler_and_is_reported(agent, es):
    seen = []

    async def run():
        model = agent()
        model.on_tool = lambda name, arguments=None: seen.append(name)
        try:
            return "".join([piece async for piece in model.answer("algo lento")])
        finally:
            await model.close()
    said = asyncio.run(run())
    assert any(said.startswith(w) for w in i18n.L.list("speech.wait")) and said.endswith("Soleado.")
    assert seen == ["get_weather"]


def test_failures_are_unavailable(agent, es):
    with pytest.raises(Unavailable) as found:
        talk(agent, "sin límite")
    assert found.value.sentence == i18n.L("speech.llm_limit", name=agent.NAME)
    with pytest.raises(Unavailable) as found:
        talk(agent, "se muere")
    assert found.value.sentence == i18n.L("speech.llm_cut", name=agent.NAME)


def test_after_dying_the_next_question_starts_another(agent, es):
    async def run():
        model = agent()
        try:
            with pytest.raises(Unavailable):
                [piece async for piece in model.answer("se muere")]
            return "".join([piece async for piece in model.answer("hola")])
        finally:
            await model.close()
    assert asyncio.run(run()) == "Hola, ¿qué tal?"


def test_complete_is_one_answer_apart(agent):
    async def run():
        model = agent()
        try:
            return await model.complete("hola"), await model.complete("manda una nota")
        finally:
            await model.close()
    assert asyncio.run(run()) == ("Hola, ¿qué tal?", "Vale, no.")  # no tools at all there
    new = [m["params"] for m in agent.received() if m.get("method") == "session/new"]
    assert all(p["mcpServers"] == [] for p in new)


def test_ready(agent, monkeypatch, tmp_path):
    monkeypatch.setattr(gemini.Path, "home", lambda: tmp_path)
    for key in ("GEMINI_API_KEY", "GOOGLE_API_KEY", "GOOGLE_GENAI_USE_VERTEXAI"):
        monkeypatch.delenv(key, raising=False)
    if agent is gemini.Gemini:
        assert agent.ready() == "Gemini CLI isn't signed in"
        monkeypatch.setenv("GEMINI_API_KEY", "x")
    assert agent.ready() is None
    monkeypatch.setenv("PATH", "/nonexistent")
    assert agent.ready().endswith("isn't installed")


# Gemini's own


def test_gemini_runs_with_jarvis_policy_and_tools(gemini_agent):
    agent = gemini_agent
    paths.PERMISSIONS.write_text('{"allowed": {"anyassistant": ["get_status", "set_timer"]}}')
    talk(agent, "hola")
    start = next(m for m in agent.received() if "argv" in m)
    assert start["argv"][:2] == ["--acp", "--admin-policy"]  # above your own policies
    policy = open(start["argv"][2]).read()
    assert 'toolName = "*"\ndecision = "deny"' in policy and 'toolName = "google_web_search"' in policy
    assert 'mcpName = "*"\ndecision = "ask_user"' in policy
    assert 'toolName = ["get_status", "set_timer"]' in policy  # only those of Jarvis's
    new = next(m["params"] for m in agent.received() if m.get("method") == "session/new")
    assert new["mcpServers"] == [{"type": "http", "name": "anyassistant",
                                  "url": "http://127.0.0.1:8080/mcp?device=ipad", "headers": []}]


def test_gemini_without_its_policy_doesnt_run(gemini_agent, monkeypatch, es):
    agent = gemini_agent
    monkeypatch.setenv("FAKE_ACP_POLICY_ERROR", "1")
    with pytest.raises(Unavailable) as found:
        talk(agent, "hola")
    assert found.value.sentence == i18n.L("speech.gemini_unsafe")
    assert not prompts(agent)


def test_gemini_an_account_google_no_longer_takes(gemini_agent, monkeypatch, es):
    agent = gemini_agent
    monkeypatch.setenv("FAKE_ACP_INELIGIBLE", "1")
    with pytest.raises(Unavailable) as found:
        talk(agent, "hola")
    assert found.value.sentence == i18n.L("speech.gemini_ineligible")


def test_gemini_tool_from_its_title():
    model = object.__new__(gemini.Gemini)
    call = {"title": "send_note (family MCP Server)",
            "content": [{"type": "content", "content": {"type": "text", "text": '{"text": "hola"}'}}]}
    assert model.tool(call) == ("family", "send_note", {"text": "hola"}, "family: send note: hola")
    assert model.tool({"title": "rm -rf /"})[:2] == ("", "rm -rf /")  # unknown: it still asks


# OpenCode's own


def test_opencode_runs_with_its_permissions_on_top_of_yours(opencode_agent):
    agent = opencode_agent
    paths.PERMISSIONS.write_text('{"allowed": {"anyassistant": "all"}}')
    talk(agent, "hola")
    start = next(m for m in agent.received() if "argv" in m)
    assert start["argv"] == ["acp"]
    config = json.loads(start["env"]["OPENCODE_CONFIG_CONTENT"])
    assert list(config["permission"].items())[0] == ("*", "ask")  # every tool asks Jarvis
    assert config["permission"]["websearch"] == "allow" and config["permission"]["anyassistant_*"] == "allow"
    assert config["mcp"]["anyassistant"] == {"type": "remote", "url": "http://127.0.0.1:8080/mcp?device=ipad"}


def test_opencode_reads_of_your_servers_are_allowed(monkeypatch, tmp_path):
    (tmp_path / "opencode.jsonc").write_text('{\n  // mine\n  "mcp": {"holded": {"type": "remote", "url": "https://x"}}\n}')
    monkeypatch.setattr(opencode, "CONFIG", tmp_path)
    model = object.__new__(opencode.OpenCode)
    model.model, model.device = "opencode/beam-free", None
    config = model.config()
    assert config["permission"]["holded_get_*"] == "allow" and "holded_create_*" not in config["permission"]
    assert config["model"] == "opencode/beam-free"


def test_opencode_tool_from_its_code():
    model = object.__new__(opencode.OpenCode)
    code = "const w = await tools.family.get_weather({});\nawait tools.family.send_note({text: 'hola'});"
    assert model.tool({"title": "execute", "rawInput": {"code": code}})[:2] == ("family", "send_note")
    hidden = "const t = tools['family']; await t.send_note({});"
    found = model.tool({"title": "execute", "rawInput": {"code": hidden}})
    assert found[:2] == ("", "execute") and "send_note" in found[3]  # unknown: it asks, saying the code
    assert model.tool({"title": "/etc/hosts", "kind": "read", "rawInput": {"path": "/etc/hosts"}}) is None
    assert model.tool({"title": "shell", "kind": "execute", "rawInput": {"command": "ls"}}) is None


def test_opencode_without_its_provider(opencode_agent, es):
    agent = opencode_agent
    with pytest.raises(Unavailable) as found:
        talk(agent, "sin proveedor")
    assert found.value.sentence == i18n.L("speech.opencode_provider", command="opencode auth login")


def test_cut_off_while_it_waits_nobody_is_asked_any_more(agent, es):
    paths.PERMISSIONS.write_text("{}")

    async def run():
        model = agent()
        try:
            answer = model.answer("manda una nota")
            async for piece in answer:
                if "¿Lo hago?" in piece:
                    break  # the user said something else: the answer is cut off
            await answer.aclose()
            await asyncio.sleep(0.3)
            return store.pending()
        finally:
            await model.close()
    assert asyncio.run(run()) is None
