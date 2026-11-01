"""A fake ACP agent for tests/test_acp.py: `gemini --acp` or `opencode acp` (by the name it is run
with), speaking the Agent Client Protocol as the real ones do (Gemini CLI 0.58, OpenCode 2.0,
trimmed). What it receives, and its arguments and environment, go to $FAKE_ACP_LOG, a JSON line
each. What it answers depends on the prompt's words."""

import json
import os
import sys
import time

LOG = os.environ.get("FAKE_ACP_LOG", os.devnull)
FLAVOR = os.path.basename(sys.argv[0])  # «gemini» or «opencode»
sessions = 0
asks = 900


def log(entry):
    with open(LOG, "a") as f:
        f.write(json.dumps(entry) + "\n")


def send(message):
    print(json.dumps({"jsonrpc": "2.0", **message}), flush=True)


def update(session, **fields):
    send({"method": "session/update", "params": {"sessionId": session, "update": fields}})


def receive():
    line = sys.stdin.readline()
    if not line:
        sys.exit(0)
    message = json.loads(line)
    log(message)
    return message


def chunk(session, text):
    update(session, sessionUpdate="agent_message_chunk", content={"type": "text", "text": text})


def permission(session, server, tool, arguments, own=None):
    """Asks before a tool, as each of them does; True if the client allowed it."""
    global asks
    asks += 1
    if own:  # one of its own tools
        call = {"toolCallId": "c1", "title": own, "kind": "read", "rawInput": {"path": "/etc/hosts"}}
    elif FLAVOR == "gemini":
        call = {"toolCallId": "c1", "title": f"{tool} ({server} MCP Server)", "kind": "other",
                "content": [{"type": "content", "content": {"type": "text", "text": json.dumps(arguments)}}]}
    else:  # OpenCode: from the code it wrote
        call = {"toolCallId": "c1", "title": "execute", "kind": "other",
                "rawInput": {"code": f"const r = await tools.{server}.{tool}({json.dumps(arguments)});\nreturn r;"}}
    options = [{"optionId": "once", "kind": "allow_once", "name": "Allow once"},
               {"optionId": "always", "kind": "allow_always", "name": "Always allow"},
               {"optionId": "reject", "kind": "reject_once", "name": "Reject"}]
    send({"id": asks, "method": "session/request_permission",
          "params": {"sessionId": session, "toolCall": call, "options": options}})
    while True:
        message = receive()
        if message.get("id") == asks and "method" not in message:
            outcome = message["result"]["outcome"]
            return outcome.get("outcome") == "selected" and outcome.get("optionId") in ("once", "always")


def prompt(number, params):
    session = params["sessionId"]
    text = " ".join(b.get("text", "") for b in params["prompt"] if b["type"] == "text")
    result = {"stopReason": "end_turn"}
    if "nota" in text or "lista" in text:  # a tool that changes something, or one that reads
        tool = "send_note" if "nota" in text else "get_lists"
        update(session, sessionUpdate="tool_call", toolCallId="c1", title=tool, kind="other", status="pending")
        # OpenCode's own rules (Jarvis's «family_get_*»: allow) let reads through without asking.
        if FLAVOR == "opencode" and tool.startswith("get_") or permission(session, "family", tool, {"text": "hola"}):
            update(session, sessionUpdate="tool_call_update", toolCallId="c1", status="completed")
            chunk(session, "Hecho.")
        else:
            update(session, sessionUpdate="tool_call_update", toolCallId="c1", status="failed")
            chunk(session, "Vale, no.")
    elif "fichero" in text:  # one of its own tools: refused, OpenCode ends the turn
        if not permission(session, "", "", {}, own="/etc/hosts"):
            result = {"stopReason": "cancelled"}
    elif "lento" in text:
        update(session, sessionUpdate="tool_call", toolCallId="c2", title="get_weather", kind="other", status="pending")
        time.sleep(0.5)
        update(session, sessionUpdate="tool_call_update", toolCallId="c2", status="completed")
        chunk(session, "Soleado.")
    elif "límite" in text:
        message = "Internal error: Free usage limit reached." if FLAVOR == "opencode" else "Quota exceeded: RESOURCE_EXHAUSTED"
        send({"id": number, "error": {"code": -32603, "message": message}})
        return
    elif "proveedor" in text:
        send({"id": number, "error": {"code": -32000, "message": "Authentication required: provider authentication required"}})
        return
    elif "muere" in text:
        sys.exit(1)
    else:
        chunk(session, "Hola")
        chunk(session, ", ¿qué tal?")
    send({"id": number, "result": result})


def main():
    global sessions
    log({"argv": sys.argv[1:], "env": {k: v for k, v in os.environ.items() if k.startswith(("OPENCODE_", "GEMINI_"))}})
    if os.environ.get("FAKE_ACP_POLICY_ERROR"):
        print("[ADMIN] Policy file error in policy.toml:", file=sys.stderr, flush=True)
    while True:
        message = receive()
        method, number, params = message.get("method"), message.get("id"), message.get("params") or {}
        if method == "initialize":
            send({"id": number, "result": {"protocolVersion": 1, "agentCapabilities": {
                "promptCapabilities": {"image": True}, "mcpCapabilities": {"http": True}}}})
        elif method == "session/new":
            if os.environ.get("FAKE_ACP_INELIGIBLE"):
                send({"id": number, "error": {"code": -32000, "message": "This client is no longer supported for "
                      "Gemini Code Assist for individuals. To continue using Gemini, please migrate to Antigravity"}})
                continue
            sessions += 1
            if FLAVOR == "gemini":  # it reads its system prompt now
                log({"system": open(os.environ["GEMINI_SYSTEM_MD"]).read()})
            send({"id": number, "result": {"sessionId": f"session-{sessions}"}})
        elif method == "session/prompt":
            prompt(number, params)
        elif number is not None:
            send({"id": number, "result": {}})


if __name__ == "__main__":
    main()
