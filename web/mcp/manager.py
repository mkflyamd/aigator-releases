"""MCP Connection Manager — loads cached connections at startup, handles add/remove/health."""
from __future__ import annotations

import logging
import re
import threading
import time

import shared
from config import load_config as _load_config, save_config as _save_config
from mcp.generic_client import GenericMCPClient
from mcp.stdio_client import StdioMCPClient, CommandNotFoundError
from mcp.connection_fixer import suggest_fix, is_recoverable

_log = logging.getLogger(__name__)

# Serialises add_or_update / remove so the load → modify → save → register
# section is atomic. One lock for the whole module — these are not hot paths.
_MUTATION_LOCK = threading.Lock()


def _load_connections() -> list[dict]:
    raw = _load_config().get("mcp_connections", [])
    conns: list[dict] = []
    for c in raw:
        if not isinstance(c, dict):
            _log.warning("[mcp] skipping malformed connection entry (not a dict): %r", c)
            continue
        # Migration: records saved before the transport field defaulted to HTTP.
        if "transport" not in c:
            c["transport"] = "http"
        conns.append(c)
    return conns


def _save_connections(connections: list[dict]) -> None:
    cfg = _load_config()
    cfg["mcp_connections"] = connections
    _save_config(cfg)


def _slugify(text: str) -> str:
    text = text.lower().strip()
    text = re.sub(r"[^a-z0-9]+", "-", text)
    return text.strip("-") or "mcp"


def _client_for(conn: dict):
    """Instantiate the right client class for a connection's transport."""
    if conn.get("transport") == "stdio":
        return StdioMCPClient({
            "command": conn["command"],
            "args": conn.get("args", []),
            "env": conn.get("env", {}),
            "name": conn.get("name", ""),
        })
    return GenericMCPClient({
        "url": conn["url"],
        "auth_type": conn.get("auth_type", "none"),
        "auth_value": conn.get("auth_value", ""),
        "name": conn.get("name", ""),
    })


def _register(conn: dict) -> None:
    """Register a connection's cached tools into shared registries."""
    skill_id = conn["id"]
    prefix = skill_id + "__"
    name = conn.get("name", skill_id)

    tool_names: set[str] = set()
    for t in conn.get("cached_tools", []):
        namespaced = prefix + t["name"]
        tool_def = {
            "name": namespaced,
            "description": t.get("description", ""),
            "input_schema": t.get("input_schema", {"type": "object", "properties": {}}),
        }
        if not any(d["name"] == namespaced for d in shared.TOOLS):
            shared.TOOLS.append(tool_def)

        orig_name = t["name"]
        conn_snapshot = dict(conn)  # closure capture — full record so _client_for has everything

        def _make_handler(orig_name: str, c: dict):
            def _handler(**kwargs):
                transport = c.get("transport", "http")
                client = None
                try:
                    client = _client_for(c)
                    return {"result": client.call(orig_name, kwargs)}
                except CommandNotFoundError as e:
                    return {"error": f"Command not found: {e}", "transport": transport}
                except TimeoutError as e:
                    return {"error": f"MCP server timed out: {e}", "transport": transport}
                except RuntimeError as e:
                    return {"error": f"MCP call failed: {e}", "transport": transport}
                except Exception as e:
                    return {"error": f"Unexpected MCP error: {e}", "transport": transport}
                finally:
                    if client is not None:
                        close = getattr(client, "close", None)
                        if close:
                            try:
                                close()
                            except Exception:
                                pass
            return _handler

        shared.TOOL_DISPATCH[namespaced] = _make_handler(orig_name, conn_snapshot)
        shared.TOOL_STATUS[namespaced] = f"Calling {name}..."
        tool_names.add(namespaced)

    shared.SKILL_TOOLS_MAP.setdefault(skill_id, set()).update(tool_names)


def _unregister(skill_id: str) -> None:
    """Remove all tools for a connection from shared registries."""
    prefix = skill_id + "__"
    shared.TOOLS[:] = [d for d in shared.TOOLS if not d["name"].startswith(prefix)]
    for key in list(shared.TOOL_DISPATCH):
        if key.startswith(prefix):
            del shared.TOOL_DISPATCH[key]
    for key in list(shared.TOOL_STATUS):
        if key.startswith(prefix):
            del shared.TOOL_STATUS[key]
    shared.SKILL_TOOLS_MAP.pop(skill_id, None)


def load_all_from_cache() -> None:
    """Called at app startup — registers all enabled connections from cached tool schemas. No network calls."""
    for conn in _load_connections():
        if not conn.get("enabled", True):
            continue
        if not conn.get("cached_tools"):
            continue
        _register(conn)


def _connect_http_with_fixer(provisional: dict) -> tuple[object | None, dict, str]:
    """Try to instantiate GenericMCPClient. On recoverable failure, ask the LLM
    for a URL variant and retry. Returns (client, final_provisional, error).
    client is None on terminal failure.
    """
    tried: list[str] = []
    current = dict(provisional)
    last_error = ""
    raw_input = provisional["url"]

    for attempt in range(3):  # original + up to 2 LLM suggestions
        tried.append(current["url"])
        try:
            client = _client_for(current)
            if attempt > 0:
                _log.info("[fixer] connected on attempt %d with %s", attempt + 1, current["url"])
            return client, current, ""
        except (ValueError, RuntimeError) as e:
            last_error = str(e)
            _log.info("[fixer] attempt %d failed for %s: %s", attempt + 1, current["url"], last_error[:160])
            if not is_recoverable(last_error):
                break
            new_url = suggest_fix(current["url"], last_error, raw_input, tried)
            if not new_url:
                break
            current = {**current, "url": new_url}

    return None, current, last_error


def add_or_update(entry: dict) -> dict:
    """Connect live to an MCP server, discover tools, cache, and register.
    Returns: {ok, id, name, tool_count} or {ok: False, error: str}
    """
    transport = entry.get("transport", "http")

    if transport == "stdio":
        command = (entry.get("command") or "").strip()
        if not command:
            return {"ok": False, "error": "command is required for stdio transport"}
        provisional = {
            "transport": "stdio",
            "command": command,
            "args": list(entry.get("args", [])),
            "env": dict(entry.get("env", {})),
            "name": entry.get("name", "") or "",
        }
    else:
        url = entry.get("url", "").strip().rstrip("/")
        if not url:
            return {"ok": False, "error": "URL is required"}
        provisional = {
            "transport": "http",
            "url": url,
            "auth_type": entry.get("auth_type", "none"),
            "auth_value": entry.get("auth_value", ""),
            "extra_headers": dict(entry.get("headers", {})),
            "name": entry.get("name", "") or "",
        }

    client = None
    try:
        if transport == "http":
            client, final_provisional, fix_err = _connect_http_with_fixer(provisional)
            if client is None:
                return {"ok": False, "error": fix_err}
            provisional = final_provisional
        else:
            try:
                client = _client_for(provisional)
            except CommandNotFoundError as e:
                return {"ok": False, "error": str(e)}
            except (ValueError, RuntimeError) as e:
                return {"ok": False, "error": str(e)}

        try:
            info = client.server_info()
            server_name = info.get("name", "") or ""
            server_version = info.get("version", "")
        except Exception as e:
            _log.warning("[mcp] could not get server info: %s", e)
            server_name = ""
            server_version = ""

        name = (entry.get("name") or "").strip() or server_name or provisional.get("url") or provisional.get("command") or "mcp"
        skill_id = "mcp-" + _slugify(name)

        try:
            raw_tools = client.list_tools()
        except Exception as e:
            return {"ok": False, "error": f"Could not list tools: {e}"}

        if not raw_tools:
            return {"ok": False, "error": "This server returned no tools"}
    finally:
        if client is not None:
            close = getattr(client, "close", None)
            if close:
                close()

    cached_tools = [
        {
            "name": t["name"],
            "description": t.get("description", ""),
            "input_schema": t.get("inputSchema", {"type": "object", "properties": {}}),
        }
        for t in raw_tools
    ]

    conn = {
        "id": skill_id,
        "name": name,
        "transport": transport,
        "enabled": True,
        "server_info": {"name": server_name, "version": server_version},
        "cached_tools": cached_tools,
    }
    if transport == "stdio":
        conn["command"] = provisional["command"]
        conn["args"] = provisional["args"]
        conn["env"] = provisional["env"]
    else:
        conn["url"] = provisional["url"]
        conn["auth_type"] = provisional["auth_type"]
        conn["auth_value"] = provisional["auth_value"]
        conn["extra_headers"] = provisional.get("extra_headers", {})

    with _MUTATION_LOCK:
        connections = _load_connections()
        existing_idx = next((i for i, c in enumerate(connections) if c["id"] == skill_id), None)
        if existing_idx is not None:
            connections[existing_idx] = conn
        else:
            connections.append(conn)
        _save_connections(connections)

        _unregister(skill_id)
        _register(conn)

    return {"ok": True, "id": skill_id, "name": name, "tool_count": len(cached_tools)}


def remove(connection_id: str) -> dict:
    """Remove a connection — unregisters tools and deletes from config."""
    with _MUTATION_LOCK:
        connections = _load_connections()
        updated = [c for c in connections if c["id"] != connection_id]
        if len(updated) == len(connections):
            return {"ok": False, "error": "Connection not found"}
        _save_connections(updated)
        _unregister(connection_id)
    return {"ok": True}


def health_check(connection_id: str) -> dict:
    """Ping one MCP server. Returns {ok, latency_ms} or {ok: False, error}."""
    connections = _load_connections()
    conn = next((c for c in connections if c["id"] == connection_id), None)
    if not conn:
        return {"ok": False, "error": "Connection not found"}
    t0 = time.monotonic()
    client = None
    try:
        client = _client_for(conn)
        client.server_info()
        latency_ms = int((time.monotonic() - t0) * 1000)
        return {"ok": True, "latency_ms": latency_ms}
    except Exception as e:
        return {"ok": False, "error": str(e)}
    finally:
        if client is not None:
            close = getattr(client, "close", None)
            if close:
                close()


def list_with_status() -> list[dict]:
    """Return all connections. Does not probe servers — use the /health endpoint for live status."""
    out = []
    for conn in _load_connections():
        row = {
            "id": conn["id"],
            "name": conn["name"],
            "transport": conn.get("transport", "http"),
            "enabled": conn.get("enabled", True),
            "tool_count": len(conn.get("cached_tools", [])),
            "connected": None,
        }
        if conn.get("transport") == "stdio":
            row["command"] = conn.get("command", "")
            row["args"] = conn.get("args", [])
        else:
            row["url"] = conn.get("url", "")
            row["auth_type"] = conn.get("auth_type", "none")
        out.append(row)
    return out
