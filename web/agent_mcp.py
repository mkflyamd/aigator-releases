"""The front door agents use to wake each other: a small MCP server over HTTP.

Each agent Gator launches gets its own secret in GATOR_AGENT_TOKEN and an MCP
config that sends it as a bearer token. Gator keeps token -> terminal, so who is
asking always comes from that record and never from anything the agent writes.

This app is mounted outside the route table on purpose (see app.py). The CSRF check
protects routes that the browser UI calls with ambient credentials; agents never hold
the CSRF token, and this door is guarded by the per-session bearer token instead.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import secrets
import threading
from pathlib import Path

from starlette.requests import Request
from starlette.responses import JSONResponse, Response

import agent_state
import agent_suspend
import agent_wake
import generic_agent
from agent_capabilities import relayable
from relay.model import META_KEY, TaskState, pty_endpoint
from relay.service import get_relay

logger = logging.getLogger(__name__)

TOKEN_ENV = "GATOR_AGENT_TOKEN"
SERVER_NAME = "gator"
MOUNT_PATH = "/agent-mcp"
TOOL_NAME = "message_agent"
PROTOCOLS = ("2025-06-18", "2025-03-26", "2024-11-05")

INSTRUCTIONS = (
    "AI Gator can wake a suspended agent session and hand it one message: use the "
    f"{TOOL_NAME} tool. If a peer is not in ListAgents, it may be suspended: check "
    "~/.gator/wake/targets.json for its name, then call the tool with that name."
)
TOOL = {
    "name": TOOL_NAME,
    "description": (
        "Send one message to another agent session in this project, waking it if "
        "AI Gator suspended it. Name it by session name or session id. The recipient sees "
        "who sent it. Only existing sessions are woken."
    ),
    "inputSchema": {
        "type": "object",
        "properties": {
            "to": {"type": "string", "description": "Session name (as /rename set it) or session id."},
            "message": {"type": "string", "description": f"Plain text, at most {agent_wake.MESSAGE_MAX_BYTES} bytes."},
        },
        "required": ["to", "message"],
        "additionalProperties": False,
    },
}

_lock = threading.Lock()


def _tokens_file() -> Path:
    return agent_suspend.targets_file().parent / "tokens.json"


def _load_tokens() -> dict[str, dict]:
    try:
        found = json.loads(_tokens_file().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return {k: v for k, v in found.items() if isinstance(v, dict) and "pty_id" in v} if isinstance(found, dict) else {}


# Digests only, kept on disk so agents that outlive a backend restart (their terminals
# live in the PTY host) can still call the tool.
_tokens: dict[str, dict] = _load_tokens()


def _save_tokens() -> None:
    try:
        agent_suspend._write_atomic(_tokens_file(), json.dumps(_tokens))
    except OSError:
        logger.warning("could not save the agent tokens", exc_info=True)


def _digest(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def _update(change) -> None:
    """Apply a change on top of what is on disk: another backend instance may have
    issued or revoked tokens since this one last looked."""
    with _lock:
        fresh = _load_tokens()
        change(fresh)
        _tokens.clear()
        _tokens.update(fresh)
        _save_tokens()


def issue(pty_id: str, project_id: str | None, agent: str = "claude") -> str:
    """A new token for this terminal. A terminal that is launched again (a wake reuses
    its id) replaces its old token."""
    token = secrets.token_urlsafe(32)

    def add(tokens: dict) -> None:
        for key in [k for k, v in tokens.items() if v["pty_id"] == pty_id]:
            del tokens[key]
        tokens[_digest(token)] = {"pty_id": pty_id, "project_id": project_id, **({} if agent == "claude" else {"agent": agent})}

    _update(add)
    return token


def holds_token(pty_id: str) -> bool:
    with _lock:
        return any(v["pty_id"] == pty_id for v in _tokens.values())


def revoke(pty_id: str) -> None:
    """The terminal is closed: its token stops working."""

    def drop(tokens: dict) -> None:
        for key in [k for k, v in tokens.items() if v["pty_id"] == pty_id]:
            del tokens[key]

    _update(drop)


def caller_for(token: str | None) -> dict | None:
    if not token:
        return None
    with _lock:
        found = _tokens.get(_digest(token))
    return dict(found) if found else None


def backend_port() -> str:
    import pty_client

    port = pty_client.instance_key()
    return port if port.isdigit() else "8000"


def mcp_config_path() -> str:
    """The MCP config Claude is launched with; the token itself stays in the environment."""
    agent_state.HOOKS_DIR.mkdir(parents=True, exist_ok=True)
    port = backend_port()
    path = agent_state.HOOKS_DIR / f"gator-mcp-{port}.json"
    body = json.dumps(
        {
            "mcpServers": {
                SERVER_NAME: {
                    "type": "http",
                    "url": f"http://127.0.0.1:{port}{MOUNT_PATH}/",
                    "headers": {"Authorization": f"Bearer ${{{TOKEN_ENV}}}"},
                }
            }
        },
        indent=2,
    )
    if not path.exists() or path.read_text(encoding="utf-8") != body:
        path.write_text(body, encoding="utf-8")
    return str(path)


def crush_mcp_line() -> str:
    """The crushrc line that gives Crush the same door; the token is read from the environment at launch."""
    url = f"http://127.0.0.1:{backend_port()}{MOUNT_PATH}/"
    return f'mcp add {SERVER_NAME} --type http --url {url} --header Authorization "Bearer ${TOKEN_ENV}"'


def serves(agent: str, command: list[str] | None) -> bool:
    return relayable(agent) and bool(command) and not agent_state.is_wsl_command(command)


def launch_env(agent: str, command: list[str] | None, pty_id: str, project_id: str | None) -> dict[str, str]:
    return {TOKEN_ENV: issue(pty_id, project_id, agent)} if serves(agent, command) else {}


def with_gator_mcp(agent: str, command: list[str] | None) -> list[str] | None:
    if agent != "claude" or not serves(agent, command):
        return command
    return [*command, "--mcp-config", mcp_config_path()]


async def _sender(caller: dict) -> dict:
    """Who is asking, from Gator's own records of that terminal."""
    session_id = generic_agent.linked_session_id(caller["pty_id"]) or agent_state.read_session(caller["pty_id"]) or ""
    agent = caller.get("agent", "claude")
    title = await asyncio.to_thread(agent_wake.title_of, caller["project_id"], agent, session_id) if session_id else ""
    return {
        "name": title or session_id[:8] or "another agent",
        "session_id": session_id,
        "project_id": caller["project_id"],
        "pty_id": caller["pty_id"],
    }


def _text_result(text: str, is_error: bool = False) -> dict:
    return {"content": [{"type": "text", "text": text}], "isError": is_error}


async def _call_tool(caller: dict, arguments: dict) -> dict:
    to, message = arguments.get("to"), arguments.get("message")
    sender = await _sender(caller)
    if not isinstance(to, str) or not isinstance(message, str):
        reason = "Both 'to' and 'message' are required text."
        await asyncio.to_thread(agent_wake.audit_refusal, sender, to, "invalid", reason, message)
        return _text_result(reason, True)
    endpoint = pty_endpoint(caller["pty_id"], sender["name"], sender["project_id"])
    try:
        task = await get_relay().submit(endpoint, to, message)
    except Exception:
        logger.exception("relay failed")
        reason = "AI Gator could not deliver the message."
        await asyncio.to_thread(agent_wake.audit_refusal, sender, to, "failed", reason, message)
        return _text_result(reason, True)
    meta = task["metadata"][META_KEY]
    if task["status"]["state"] == TaskState.WORKING.value:
        delivered = {"status": "delivered", "woke": bool(meta.get("woke")), "target": meta["target"], "task_id": task["id"]}
        return _text_result(json.dumps(delivered))
    refused = {"status": meta["code"], "reason": task["status"]["message"]["parts"][0]["text"]}
    if "candidates" in meta:
        refused["candidates"] = meta["candidates"]
    await asyncio.to_thread(agent_wake.audit_refusal, sender, to, refused["status"], refused["reason"], message)
    return _text_result(json.dumps(refused), True)


def _rpc_error(request_id, code: int, message: str) -> dict:
    return {"jsonrpc": "2.0", "id": request_id, "error": {"code": code, "message": message}}


async def _dispatch(caller: dict, body: dict) -> dict | None:
    method, request_id, params = body.get("method"), body.get("id"), body.get("params") or {}
    if request_id is None:
        return None
    if method == "initialize":
        wanted = params.get("protocolVersion")
        result = {
            "protocolVersion": wanted if wanted in PROTOCOLS else PROTOCOLS[0],
            "capabilities": {"tools": {}},
            "serverInfo": {"name": SERVER_NAME, "version": "1"},
            "instructions": INSTRUCTIONS,
        }
    elif method == "ping":
        result = {}
    elif method == "tools/list":
        result = {"tools": [TOOL]}
    elif method == "tools/call":
        if params.get("name") != TOOL_NAME:
            return _rpc_error(request_id, -32602, "Unknown tool.")
        result = await _call_tool(caller, params.get("arguments") or {})
    else:
        return _rpc_error(request_id, -32601, "Method not found.")
    return {"jsonrpc": "2.0", "id": request_id, "result": result}


def _terminal_alive(pty_id: str) -> bool:
    """False only when the terminal is known to be gone. A PTY host that cannot be
    reached or does not answer keeps the token: a live agent must not lose it to a hiccup."""
    import pty_client
    from routes import terminal

    entry = terminal._pty_sessions.get(pty_id)
    if entry is not None:
        return not entry.done
    if not pty_client.host_enabled():
        return False
    info = pty_client.find_host(pty_client.instance_key())
    if info is None:
        return True
    try:
        status = pty_client.host_request(info, {"op": "status", "id": pty_id})
    except pty_client.HostError:
        return True
    return bool(status.get("exists")) and not status.get("done")


def _bearer(request: Request) -> str | None:
    scheme, _, value = request.headers.get("authorization", "").partition(" ")
    return value.strip() if scheme.lower() == "bearer" else None


async def _respond(request: Request) -> Response:
    token = _bearer(request)
    caller = caller_for(token)
    reason = "No token was sent." if not token else "The token is not known or was revoked."
    # A terminal that exited by itself never went through close, so its token is checked here.
    if caller is not None and not await asyncio.to_thread(_terminal_alive, caller["pty_id"]):
        revoke(caller["pty_id"])
        caller = None
        reason = "The terminal that held this token has ended."
    if caller is None:
        await asyncio.to_thread(agent_wake.audit_refusal, None, "", "unauthorized", reason, "")
        return JSONResponse({"error": "unauthorized"}, status_code=401, headers={"WWW-Authenticate": "Bearer"})
    if request.method != "POST":
        return Response(status_code=405, headers={"Allow": "POST"})
    try:
        body = await request.json()
    except ValueError:
        body = None
    if not isinstance(body, dict):
        return JSONResponse(_rpc_error(None, -32700, "Expected one JSON-RPC message."), status_code=400)
    reply = await _dispatch(caller, body)
    return Response(status_code=202) if reply is None else JSONResponse(reply)


async def app(scope, receive, send):
    if scope["type"] == "websocket":
        await send({"type": "websocket.close", "code": 1008})
        return
    if scope["type"] != "http":
        return
    response = await _respond(Request(scope, receive))
    await response(scope, receive, send)
