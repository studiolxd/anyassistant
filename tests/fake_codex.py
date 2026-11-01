"""A fake `codex` for tests/test_codex.py: `codex app-server` speaking its JSON-RPC (what the real
one 0.155 sends, trimmed), `codex login status` and `codex exec`. What it receives goes to
$FAKE_CODEX_LOG, a JSON line each. What it answers depends on the question's words."""

import json
import os
import select
import sys
import time

LOG = os.environ.get("FAKE_CODEX_LOG", os.devnull)


def log(entry):
    with open(LOG, "a") as f:
        f.write(json.dumps(entry) + "\n")


def send(message):
    print(json.dumps({"jsonrpc": "2.0", **message}), flush=True)


def notify(method, **params):
    send({"method": method, "params": params})


def receive():
    line = sys.stdin.readline()
    if not line:
        sys.exit(0)
    message = json.loads(line)
    log(message)
    return message


def delta(turn, text):
    notify("item/agentMessage/delta", threadId="t", turnId=turn, itemId="m", delta=text)


def tool_call(turn, server, tool, arguments, status="inProgress"):
    item = {"type": "mcpToolCall", "id": "exec-1", "server": server, "tool": tool, "status": status,
            "arguments": arguments}
    notify("item/started" if status == "inProgress" else "item/completed", item=item, threadId="t", turnId=turn)


def approval(turn, server, tool, arguments):
    """Codex asks its client before an MCP tool; True if the client accepted."""
    send({"id": 900, "method": "mcpServer/elicitation/request", "params": {
        "threadId": "t", "turnId": turn, "serverName": server, "mode": "form",
        "_meta": {"codex_approval_kind": "mcp_tool_call", "persist": ["session", "always"],
                  "tool_params": arguments},
        "message": f'Allow the {server} MCP server to run tool "{tool}"?',
        "requestedSchema": {"type": "object", "properties": {}}}})
    while True:
        message = receive()
        if message.get("id") == 900 and "method" not in message:
            return message["result"]["action"] == "accept"


def turn_completed(turn, status="completed", error=None):
    notify("turn/completed", threadId="t", turn={"id": turn, "status": status, "error": error})


def play(turn, text):
    if "nota" in text or "lista" in text:  # a tool that changes something, or one that reads
        tool = "send_note" if "nota" in text else "get_lists"
        tool_call(turn, "family", tool, {"text": "hola"})
        if approval(turn, "family", tool, {"text": "hola"}):
            tool_call(turn, "family", tool, {"text": "hola"}, status="completed")
            delta(turn, "Hecho.")
        else:
            tool_call(turn, "family", tool, {"text": "hola"}, status="failed")
            delta(turn, "¿La mando?")
    elif "lento" in text:  # a slow tool, before any text
        tool_call(turn, "anyassistant", "get_weather", {})
        time.sleep(0.5)
        tool_call(turn, "anyassistant", "get_weather", {}, status="completed")
        delta(turn, "Soleado.")
    elif "sesión" in text:  # signed out: it would retry five times
        notify("error", threadId="t", turnId=turn, willRetry=True, error={
            "message": "Reconnecting... 1/5", "codexErrorInfo": {"responseStreamDisconnected": {"httpStatusCode": 401}}})
        # It goes on retrying (the real one, five times) unless the client interrupts the turn.
        while select.select([sys.stdin], [], [], 5)[0]:
            message = receive()
            if message.get("method") == "turn/interrupt":
                send({"id": message["id"], "result": {}})
                break
        turn_completed(turn, "interrupted")
        return
    elif "límite" in text:
        turn_completed(turn, "failed", {"message": "usage limit", "codexErrorInfo": "usageLimitExceeded"})
        return
    elif "muere" in text:
        sys.exit(1)
    else:
        delta(turn, "Hola")
        delta(turn, ", ¿qué tal?")
    turn_completed(turn)


def app_server():
    threads = turns = 0
    while True:
        message = receive()
        method, number = message.get("method"), message.get("id")
        if method == "initialize":
            send({"id": number, "result": {"userAgent": "fake"}})
        elif method == "thread/start":
            threads += 1
            send({"id": number, "result": {"thread": {"id": f"thread-{threads}"}}})
        elif method == "turn/start":
            turns += 1
            turn = f"turn-{turns}"
            send({"id": number, "result": {"turn": {"id": turn, "status": "inProgress"}}})
            text = " ".join(i.get("text", "") for i in message["params"]["input"])
            play(turn, text)
        elif method == "turn/interrupt":
            send({"id": number, "result": {}})
            turn_completed(message["params"]["turnId"], "interrupted")
        elif number is not None:
            send({"id": number, "result": {}})


def main():
    arguments = sys.argv[1:]
    log({"argv": arguments})
    if arguments[:1] == ["app-server"]:
        app_server()
    elif arguments[:2] == ["login", "status"]:
        sys.exit(0 if os.environ.get("FAKE_CODEX_SIGNED_IN") else 1)
    elif arguments[:1] == ["exec"]:
        prompt = sys.stdin.read()
        out = arguments[arguments.index("--output-last-message") + 1]
        with open(out, "w") as f:
            f.write(f"Dijiste: {prompt}\n")


if __name__ == "__main__":
    main()
