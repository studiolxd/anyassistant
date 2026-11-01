"""The plugin «llm-openai»: OpenAI's API (OpenAI, Ollama, any compatible) and Hermes."""

import asyncio
import json

from aiohttp import web as aiohttp_web
from aiohttp.test_utils import TestServer

import kernel
import tools

openai = kernel.load("llm-openai")


def sse(*chunks) -> bytes:
    return b"".join(b"data: " + json.dumps(c).encode() + b"\n\n" for c in chunks) + b"data: [DONE]\n\n"


def text(piece):
    return {"choices": [{"delta": {"content": piece}}]}


def call(name, arguments):
    return {"choices": [{"delta": {"tool_calls": [{"index": 0, "id": "c1", "function": {"name": name, "arguments": arguments}}]}}]}


async def talk(answers, monkeypatch, said=("¿Qué hora es?",)):
    """A fake OpenAI service answering in order; what Jarvis heard back, and what it sent."""
    sent = []

    async def completions(request):
        body = await request.json()
        sent.append(body)
        return aiohttp_web.Response(body=answers[len(sent) - 1], content_type="text/event-stream")

    app = aiohttp_web.Application()
    app.router.add_post("/v1/chat/completions", completions)
    server = TestServer(app)
    await server.start_server()
    try:
        monkeypatch.setattr(openai.OpenAI, "url", str(server.make_url("/v1")))
        monkeypatch.setattr(openai.OpenAI, "key", lambda self: "sk-test")
        model = openai.OpenAI()
        heard = []
        for sentence in said:
            heard.append("".join([piece async for piece in model.answer(sentence)]))
        await model.close()
        return heard, sent
    finally:
        await server.close()


def test_it_streams_and_keeps_the_conversation(monkeypatch):
    monkeypatch.setattr(tools, "available", lambda: {})
    heard, sent = asyncio.run(talk([sse(text("Son "), text("las diez.")), sse(text("De nada."))], monkeypatch,
                                   said=("¿Qué hora es?", "Gracias")))
    assert heard == ["Son las diez.", "De nada."]
    second = [m["role"] for m in sent[1]["messages"]]
    assert second == ["system", "user", "assistant", "user"]  # the whole conversation, again
    assert sent[1]["model"] == "gpt-5-mini"


def test_it_runs_jarvis_tools_and_goes_on(monkeypatch):
    ran = []
    monkeypatch.setattr(tools, "available", lambda: {"set_timer": tools.Tool(lambda: None, "A timer.", {
        "type": "object", "properties": {"seconds": {"type": "integer"}}, "required": ["seconds"]}, False)})
    monkeypatch.setattr(tools, "call", lambda name, arguments: ran.append((name, arguments)) or "Timer of 5 minutes.")
    heard, sent = asyncio.run(talk([sse(call("set_timer", '{"seconds": 300}')), sse(text("Listo, cinco minutos."))],
                                   monkeypatch))
    assert ran == [("set_timer", {"seconds": 300})]
    assert heard[0].endswith("Listo, cinco minutos.")
    assert sent[0]["tools"][0]["function"]["name"] == "set_timer"
    roles = [m["role"] for m in sent[1]["messages"]]
    assert roles[-2:] == ["assistant", "tool"] and sent[1]["messages"][-1]["content"] == "Timer of 5 minutes."


def test_a_tool_that_needs_a_yes_tells_the_model_to_ask(monkeypatch):
    monkeypatch.setattr(tools, "available", lambda: {"forget": tools.Tool(lambda: None, "Forget.", {
        "type": "object", "properties": {}, "required": []}, True)})

    def refuse(name, arguments):
        raise tools.ToolError("needs the user's confirmation: ask them")

    monkeypatch.setattr(tools, "call", refuse)
    heard, sent = asyncio.run(talk([sse(call("forget", "{}")), sse(text("¿Lo olvido?"))], monkeypatch))
    assert sent[1]["messages"][-1]["content"].startswith("Error: needs the user's confirmation")
    assert heard[0].endswith("¿Lo olvido?")


def test_hermes_keeps_its_own_conversation_and_tools():
    assert openai.Hermes.session_header and not openai.Hermes.own_tools
    assert openai.OpenAI.own_tools and openai.Ollama.own_tools
