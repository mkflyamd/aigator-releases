"""Minimal MCP server that speaks newline-delimited JSON-RPC over stdio.
Used by tests/mcp/test_stdio_client.py to exercise StdioMCPClient against
a real subprocess instead of a mock.

Supports:
  - initialize           → returns serverInfo {"name": "fake", "version": "0.1"}
  - tools/list           → returns one tool "echo"
  - tools/call "echo"    → returns the args as text content
  - tools/call "later"   → answers "answered" after 1.5s, without blocking other calls
  - tools/call "crash"   → exits 1 immediately (for crash recovery tests)
  - tools/call "hang"    → sleeps forever (for timeout tests)
  - tools/call "garbage" → writes a non-JSON line to stdout
"""

import json
import os
import sys
import threading
import time

# `slow` answers only after 30s unless the client sends notifications/cancelled for it. With FAKE_MCP_LOG set,
# every slow call and every cancel notice is appended there as "call <id> <tool>" / "cancelled <id>".
_cancelled: dict = {}
_write_lock = threading.Lock()


def _log(line):
    path = os.environ.get("FAKE_MCP_LOG")
    if path:
        with open(path, "a", encoding="utf-8") as handle:
            handle.write(line + "\n")


def respond(request_id, result=None, error=None):
    msg = {"jsonrpc": "2.0", "id": request_id}
    if error is not None:
        msg["error"] = error
    else:
        msg["result"] = result
    with _write_lock:
        sys.stdout.write(json.dumps(msg) + "\n")
        sys.stdout.flush()


def _slow(req_id):
    if not _cancelled.setdefault(req_id, threading.Event()).wait(30):
        respond(req_id, {"content": [{"type": "text", "text": "late"}]})


def main():
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            req = json.loads(line)
        except json.JSONDecodeError:
            continue

        method = req.get("method")
        req_id = req.get("id")

        if method == "initialize":
            respond(
                req_id,
                {
                    "protocolVersion": "2024-11-05",
                    "capabilities": {"tools": {}},
                    "serverInfo": {"name": "fake", "version": "0.1"},
                },
            )
        elif method == "notifications/initialized":
            continue  # no response for notifications
        elif method == "notifications/cancelled":
            request_id = req.get("params", {}).get("requestId")
            _log(f"cancelled {request_id}")
            _cancelled.setdefault(request_id, threading.Event()).set()
        elif method == "tools/list":
            respond(
                req_id,
                {
                    "tools": [
                        {
                            "name": "echo",
                            "description": "Echo input",
                            "inputSchema": {
                                "type": "object",
                                "properties": {"text": {"type": "string"}},
                            },
                        }
                    ]
                },
            )
        elif method == "tools/call":
            tool = req.get("params", {}).get("name")
            args = req.get("params", {}).get("arguments", {})
            if tool == "echo":
                respond(req_id, {"content": [{"type": "text", "text": str(args)}]})
            elif tool == "pid":
                respond(req_id, {"content": [{"type": "text", "text": str(os.getpid())}]})
            elif tool == "slow":
                _log(f"call {req_id} slow")
                threading.Thread(target=_slow, args=(req_id,), daemon=True).start()
            elif tool == "later":
                _log(f"call {req_id} later")
                reply = {"content": [{"type": "text", "text": "answered"}]}
                threading.Timer(1.5, respond, args=(req_id, reply)).start()
            elif tool == "crash":
                sys.exit(1)
            elif tool == "hang":
                while True:
                    time.sleep(60)
            elif tool == "garbage":
                sys.stdout.write("this is not json\n")
                sys.stdout.flush()
            else:
                respond(
                    req_id, error={"code": -32601, "message": f"unknown tool: {tool}"}
                )
        else:
            respond(
                req_id, error={"code": -32601, "message": f"unknown method: {method}"}
            )


if __name__ == "__main__":
    main()
