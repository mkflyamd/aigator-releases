"""Minimal MCP server that speaks newline-delimited JSON-RPC over stdio.
Used by tests/mcp/test_stdio_client.py to exercise StdioMCPClient against
a real subprocess instead of a mock.

Supports:
  - initialize           → returns serverInfo {"name": "fake", "version": "0.1"}
  - tools/list           → returns one tool "echo"
  - tools/call "echo"    → returns the args as text content
  - tools/call "crash"   → exits 1 immediately (for crash recovery tests)
  - tools/call "hang"    → sleeps forever (for timeout tests)
  - tools/call "garbage" → writes a non-JSON line to stdout
"""
import json
import sys
import time


def respond(request_id, result=None, error=None):
    msg = {"jsonrpc": "2.0", "id": request_id}
    if error is not None:
        msg["error"] = error
    else:
        msg["result"] = result
    sys.stdout.write(json.dumps(msg) + "\n")
    sys.stdout.flush()


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
            respond(req_id, {
                "protocolVersion": "2024-11-05",
                "capabilities": {"tools": {}},
                "serverInfo": {"name": "fake", "version": "0.1"},
            })
        elif method == "notifications/initialized":
            continue  # no response for notifications
        elif method == "tools/list":
            respond(req_id, {"tools": [
                {"name": "echo", "description": "Echo input", "inputSchema": {"type": "object", "properties": {"text": {"type": "string"}}}}
            ]})
        elif method == "tools/call":
            tool = req.get("params", {}).get("name")
            args = req.get("params", {}).get("arguments", {})
            if tool == "echo":
                respond(req_id, {"content": [{"type": "text", "text": str(args)}]})
            elif tool == "crash":
                sys.exit(1)
            elif tool == "hang":
                while True:
                    time.sleep(60)
            elif tool == "garbage":
                sys.stdout.write("this is not json\n")
                sys.stdout.flush()
            else:
                respond(req_id, error={"code": -32601, "message": f"unknown tool: {tool}"})
        else:
            respond(req_id, error={"code": -32601, "message": f"unknown method: {method}"})


if __name__ == "__main__":
    main()
