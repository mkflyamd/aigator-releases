"""MCP Connection Manager — loads cached connections at startup, handles add/remove/health."""
from __future__ import annotations

import logging
import re
import threading
import time

import shared
from config import load_config as _load_config, save_config as _save_config
from mcp.generic_client import GenericMCPClient, OAuthRequiredError
from mcp.stdio_client import StdioMCPClient, CommandNotFoundError, acquire_pooled, release_from_pool
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


def _client_for(conn: dict, pooled: bool = True):
    """Instantiate the right client class for a connection's transport.

    For stdio, returns a pooled persistent process by default (pooled=True) so
    callers avoid spawn+init overhead on every tool call. Pass pooled=False for
    one-shot probes (dry-run / add_or_update) that need a fresh process and will
    call close() themselves.
    """
    if conn.get("transport") == "stdio":
        cfg = {
            "command": conn["command"],
            "args": conn.get("args", []),
            "env": conn.get("env", {}),
            "name": conn.get("name", ""),
        }
        if pooled:
            return acquire_pooled(cfg)
        return StdioMCPClient(cfg)
    auth_type = conn.get("auth_type", "none")
    auth_value = conn.get("auth_value", "")
    # OAuth: resolve fresh access token each call so refreshes are picked up
    if auth_type == "oauth2":
        from oauth import get_access_token
        provider_id = conn.get("oauth_provider_id", "")
        token = get_access_token(provider_id) if provider_id else ""
        if not token:
            raise RuntimeError(
                f"OAuth token expired or missing for {conn.get('name', provider_id)} — "
                "reconnect via Settings > Connections."
            )
        auth_type, auth_value = "bearer", token
    return GenericMCPClient({
        "url": conn["url"],
        "auth_type": auth_type,
        "auth_value": auth_value,
        "extra_headers": conn.get("extra_headers", {}),
        "name": conn.get("name", ""),
    })


# Common pagination/limit param names across MCP servers. If the model omits one
# of these and the schema declares it, we inject a conservative default so a "list
# all" call doesn't dump 1MB of JSON into history.
_LIMIT_PARAM_NAMES = ("limit", "maxResults", "max_results", "pageSize", "page_size",
                       "count", "top", "size", "first")
_DEFAULT_LIMIT_VALUE = 15


def _discover_limit_param(input_schema: dict) -> str | None:
    """Return the name of a limit-like param if the schema declares one, else None."""
    if not isinstance(input_schema, dict):
        return None
    props = input_schema.get("properties") or {}
    if not isinstance(props, dict):
        return None
    for name in _LIMIT_PARAM_NAMES:
        if name in props:
            spec = props[name]
            if isinstance(spec, dict) and spec.get("type") in ("integer", "number", None):
                return name
    return None


def _register(conn: dict) -> None:
    """Register a connection's cached tools into shared registries."""
    skill_id = conn["id"]
    prefix = skill_id + "__"
    name = conn.get("name", skill_id)

    tool_names: set[str] = set()
    # Annotate every tool with its connection name so the LLM can disambiguate
    # when multiple connections of the same service are registered (e.g. two
    # Jira clouds, two GitHub orgs). Without this prefix, the model has no
    # signal that "AIMT-*" should go to the AMD connection and "ROCM-*" to the
    # AMD-Hub one — it just picks whichever jira_search tool comes first.
    for t in conn.get("cached_tools", []):
        namespaced = prefix + t["name"]
        input_schema = t.get("input_schema", {"type": "object", "properties": {}})
        orig_desc = t.get("description", "")
        annotated_desc = f"[Connection: {name}] {orig_desc}".rstrip()
        tool_def = {
            "name": namespaced,
            "description": annotated_desc,
            "input_schema": input_schema,
        }
        if not any(d["name"] == namespaced for d in shared.TOOLS):
            shared.TOOLS.append(tool_def)

        orig_name = t["name"]
        conn_snapshot = dict(conn)  # closure capture — full record so _client_for has everything
        limit_param = _discover_limit_param(input_schema)

        def _make_handler(orig_name: str, c: dict, limit_param: str | None):
            def _handler(**kwargs):
                transport = c.get("transport", "http")
                # Strip internal server-injected keys (e.g. _context_id) — MCP
                # servers only accept the parameters declared in their input schema.
                kwargs = {k: v for k, v in kwargs.items() if not k.startswith("_")}
                # Inject a default limit if the schema declares one and the model omitted it.
                # Stops "list everything" calls from dumping unbounded JSON into history.
                if limit_param and limit_param not in kwargs:
                    kwargs = dict(kwargs)
                    kwargs[limit_param] = _DEFAULT_LIMIT_VALUE
                    _log.info("[mcp] injected %s=%d on %s (model omitted)",
                              limit_param, _DEFAULT_LIMIT_VALUE, orig_name)
                is_pooled = transport == "stdio"
                client = None
                try:
                    # Stdio: use pooled persistent process (no spawn overhead per call).
                    # HTTP: create a fresh client per call (stateless, matches existing pattern).
                    client = _client_for(c, pooled=is_pooled)
                    # client.call() raises McpError → RuntimeError("auth_error:...")
                    # when the server reports a tool-level failure (isError=True),
                    # so we don't need to inspect the response text for auth keywords.
                    raw = client.call(orig_name, kwargs)
                    # Some MCP servers (e.g. cloud-atlassian) return an empty string
                    # for successful mutations (POST/DELETE with no response body).
                    # Return a success sentinel so the LLM doesn't misread "" as failure
                    # and retry — causing duplicate comments/actions.
                    result_text = raw if raw else "ok"
                    return {"result": result_text}
                except CommandNotFoundError as e:
                    return {"error": f"Command not found: {e}", "transport": transport}
                except TimeoutError as e:
                    return {"error": f"MCP server timed out: {e}", "transport": transport}
                except RuntimeError as e:
                    msg = str(e)
                    is_auth = _is_auth_msg(msg) or "auth_error" in msg
                    # Strip "auth_error:<name>:" prefix so the LLM sees a clean
                    # message. The flag still gets set below for UI routing.
                    display_msg = msg
                    if msg.startswith("auth_error:"):
                        parts = msg.split(":", 2)
                        if len(parts) == 3:
                            display_msg = parts[2]
                    err = {"error": f"MCP call failed: {display_msg}", "transport": transport}
                    if is_auth:
                        err["_mcp_auth_error"] = True
                        err["_connection_id"] = c.get("id", "")
                        err["_connection_name"] = c.get("name", c.get("id", ""))
                    return err
                except Exception as e:
                    return {"error": f"Unexpected MCP error: {e}", "transport": transport}
                finally:
                    # Pooled stdio clients are owned by the pool — do not close them.
                    if client is not None and not is_pooled:
                        close = getattr(client, "close", None)
                        if close:
                            try:
                                close()
                            except Exception:
                                pass
            return _handler

        shared.TOOL_DISPATCH[namespaced] = _make_handler(orig_name, conn_snapshot, limit_param)
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


# Hints used ONLY when the server flagged isError=True — to classify the
# error as "auth" vs "other (e.g. bad probe args)" for the UX message.
_AUTH_HINT_KEYWORDS = (
    "api key", "apikey", "api-key", "x-nabu-key",
    "unauthorized", "unauthenticated", "not authenticated",
    "authentication", "auth required",
    "missing key", "missing token", "invalid token",
    "access denied", "permission denied", "forbidden",
    "credentials",
)


def _is_auth_msg(msg: str) -> bool:
    """Return True if an MCP error message looks like an auth/permission failure."""
    low = msg.lower()
    return any(kw in low for kw in _AUTH_HINT_KEYWORDS)


def _synth_value(schema: dict) -> object:
    """Generate a minimal valid placeholder for a JSON Schema fragment.
    Goal: satisfy server-side input validation so the call reaches the auth gate.
    """
    if not isinstance(schema, dict):
        return "probe"
    if "enum" in schema and isinstance(schema["enum"], list) and schema["enum"]:
        return schema["enum"][0]
    if "const" in schema:
        return schema["const"]
    for key in ("anyOf", "oneOf"):
        if isinstance(schema.get(key), list) and schema[key]:
            return _synth_value(schema[key][0])
    t = schema.get("type")
    if isinstance(t, list):
        t = next((x for x in t if x != "null"), t[0] if t else "string")
    if t == "object" or (t is None and "properties" in schema):
        return _synth_object(schema)
    if t == "array":
        return []
    if t == "string":
        return "probe"
    if t in ("integer", "number"):
        return 0
    if t == "boolean":
        return False
    if t == "null":
        return None
    return "probe"


def _synth_object(schema: dict) -> dict:
    out: dict = {}
    props = schema.get("properties") or {}
    required = schema.get("required") or []
    for name in required:
        sub = props.get(name) or {}
        out[name] = _synth_value(sub)
    return out


def _auth_was_supplied(provisional: dict) -> bool:
    """True if the user gave us credentials of any kind (so a 401 means rejection, not absence)."""
    if (provisional.get("auth_type") or "none") not in ("none", "", None):
        if provisional.get("auth_value") or provisional.get("auth_type") == "oauth2":
            return True
    for k in (provisional.get("extra_headers") or {}):
        lk = str(k).lower()
        if lk == "authorization" or lk.endswith("api-key") or lk.endswith("-key") or lk == "apikey":
            return True
    return False


def _auth_failure_message(provisional: dict) -> str:
    if _auth_was_supplied(provisional):
        return (
            "Connected — but the server rejected the credentials you provided. "
            "Double-check the token / email:api_token in the Headers field."
        )
    return (
        "Connected — found tools, but calls require authentication. "
        "Add the required auth header in the Headers field."
    )


def _probe_tools_for_auth(client, tools: list, transport: str) -> tuple[bool, str]:
    """Probe up to 3 tools and decide whether the connection is auth-gated.
    Returns (auth_fail_detected, probe_detail).

    Trust the structural `CallToolResult.isError` flag, not response text:
    - If ANY tool returns isError=False → server works, save proceeds.
    - If ALL tools return isError=True AND at least one error mentions
      auth → auth_probe_failed (block save with hint).
    - Otherwise (validation errors, bad probe args) → inconclusive, save
      proceeds; first real call will surface any auth issue.
    """
    if not tools or transport != "http":
        return False, ""

    # Extract all tools, then rank by "likely cheap and read-only" so we don't
    # accidentally invoke an LLM/action tool that takes 60s+ (e.g. nabu_chat).
    all_tools: list[tuple[str, dict]] = []
    for t in tools:
        if isinstance(t, dict):
            n = t.get("name")
            schema = t.get("inputSchema") or t.get("input_schema") or {}
        else:
            n = getattr(t, "name", None)
            schema = getattr(t, "inputSchema", None) or getattr(t, "input_schema", None) or {}
        if n:
            all_tools.append((n, schema))

    def _cheap_rank(name: str) -> int:
        # Lower = probed first.
        low = name.lower()
        cheap_prefixes = ("list_", "get_", "search_", "find_", "fetch_", "read_", "describe_", "ping", "whoami")
        if any(low.startswith(p) or low == p.rstrip("_") for p in cheap_prefixes):
            return 0
        expensive_markers = ("chat", "create_", "send_", "post_", "write_", "execute", "run_", "generate", "complete")
        if any(m in low for m in expensive_markers):
            return 2
        return 1

    all_tools.sort(key=lambda nt: _cheap_rank(nt[0]))
    candidates = all_tools[:3]
    _log.debug("[probe] probing tools=%s", [c[0] for c in candidates])

    auth_error_detail = ""
    for tool_name, schema in candidates:
        args = _synth_object(schema) if isinstance(schema, dict) else {}
        is_error, text = client.call_probe(tool_name, args)
        preview = (text or "")[:200]
        _log.debug("[probe] %s(%s) isError=%s -> %r", tool_name, list(args.keys()), is_error, preview)
        if not is_error:
            return False, ""  # Server says success — connection is good.
        if not auth_error_detail and any(kw in (text or "").lower() for kw in _AUTH_HINT_KEYWORDS):
            auth_error_detail = text[:300]

    if auth_error_detail:
        return True, auth_error_detail
    # All probes errored but none looked auth-related — likely bad synth args.
    return False, ""


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

    If `connection_id` is supplied, that record is updated in place (keeps the
    id stable on rename and lets the edit form leave secret fields blank to
    preserve what's already stored).
    """
    transport = entry.get("transport", "http")
    edit_id = (entry.get("connection_id") or "").strip()
    # When editing, look up the existing record so we can carry forward secrets
    # the user left blank (form never pre-fills full credentials).
    existing: dict | None = None
    if edit_id:
        existing = next((c for c in _load_connections() if c.get("id") == edit_id), None)
    if existing and transport == "http":
        if not (entry.get("auth_value") or "").strip():
            entry = dict(entry)
            entry["auth_value"] = existing.get("auth_value", "")
        # Pass through headers whose value is empty/blank from a masked placeholder.
        cur_headers = dict(entry.get("headers") or {})
        old_headers = existing.get("extra_headers") or {}
        for k, v in list(cur_headers.items()):
            if not str(v).strip() and k in old_headers:
                cur_headers[k] = old_headers[k]
        entry["headers"] = cur_headers
        if not (entry.get("oauth_provider_id") or "").strip() and existing.get("oauth_provider_id"):
            entry["oauth_provider_id"] = existing["oauth_provider_id"]
    elif existing and transport == "stdio":
        cur_env = dict(entry.get("env") or {})
        old_env = existing.get("env") or {}
        for k, v in list(cur_env.items()):
            if not str(v).strip() and k in old_env:
                cur_env[k] = old_env[k]
        entry["env"] = cur_env

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
        # Strip whitespace only — preserve the trailing slash. Some MCP servers
        # (e.g. Nabu) 307-redirect `/path` → `/path/` AND downgrade scheme on
        # the Location header, which loops httpx. Pass the URL exactly as the
        # user gave it; this matches GenericMCPClient's `self._url = cfg["url"]`
        # contract.
        url = entry.get("url", "").strip()
        if not url:
            return {"ok": False, "error": "URL is required"}
        # Strip whitespace from credentials and headers — pasted tokens often
        # carry trailing newlines/spaces that break header matching server-side.
        raw_headers = entry.get("headers") or {}
        clean_headers = {
            (str(k).strip()): (str(v).strip() if v is not None else "")
            for k, v in raw_headers.items()
            if str(k).strip()
        }
        clean_auth = (entry.get("auth_value") or "").strip()
        # HTTP headers must be latin-1 encodable per RFC 7230. Stray non-ASCII
        # codepoints (e.g. ○ ○ from a copy-paste of a UI status dot) cause
        # httpx to raise UnicodeEncodeError deep in the transport, surfacing as
        # an unhelpful "network:..." error. Reject up front with a precise hint.
        def _first_bad_char(s: str) -> str | None:
            for ch in s:
                if ord(ch) > 0xFF:
                    return ch
            return None
        bad = _first_bad_char(clean_auth)
        if bad:
            return {"ok": False, "error": f"Token contains a non-ASCII character ({bad!r}, U+{ord(bad):04X}). Re-paste the credential — it likely picked up a stray symbol."}
        for k, v in clean_headers.items():
            bad = _first_bad_char(k) or _first_bad_char(v)
            if bad:
                return {"ok": False, "error": f"Header '{k}' contains a non-ASCII character ({bad!r}, U+{ord(bad):04X}). Re-paste the value — it likely picked up a stray symbol."}
        provisional = {
            "transport": "http",
            "url": url,
            "auth_type": entry.get("auth_type", "none"),
            "auth_value": clean_auth,
            "extra_headers": clean_headers,
            "name": entry.get("name", "") or "",
            "oauth_provider_id": entry.get("oauth_provider_id", ""),
        }
        if provisional["auth_type"] == "oauth2" and not provisional["oauth_provider_id"]:
            return {"ok": False, "error": "OAuth flow has not completed — sign in first."}

    if entry.get("_dry_run"):
        _log.debug("[dry-run] START transport=%s", provisional.get("transport"))
        client = None
        try:
            client = _client_for(provisional, pooled=False)
            tools = client.list_tools()
            tool_count = len(tools)
            _log.debug("[dry-run] got %d tools, sample=%s", tool_count, tools[:2])
            auth_failed, probe_detail = _probe_tools_for_auth(
                client, tools, provisional.get("transport", "http")
            )
            if auth_failed:
                _log.debug("[dry-run probe] auth failure confirmed: %s", probe_detail[:120])
                return {
                    "ok": False,
                    "error": _auth_failure_message(provisional),
                    "auth_probe_failed": True,
                    "probe_detail": probe_detail,
                    "tool_count": tool_count,
                }
            return {"ok": True, "tool_count": tool_count, "name": entry.get("name", "")}
        except OAuthRequiredError as e:
            return {
                "ok": False,
                "error": "This server requires OAuth authentication.",
                "oauth_required": True,
                "oauth_metadata_url": e.metadata_url,
                "mcp_url": provisional.get("url", ""),
            }
        except Exception as exc:
            return {"ok": False, "error": str(exc)}
        finally:
            if client is not None:
                close = getattr(client, "close", None)
                if close:
                    try:
                        close()
                    except Exception:
                        pass

    client = None
    try:
        if transport == "http":
            try:
                client, final_provisional, fix_err = _connect_http_with_fixer(provisional)
            except OAuthRequiredError as e:
                return {
                    "ok": False,
                    "error": "This server requires OAuth authentication.",
                    "oauth_required": True,
                    "oauth_metadata_url": e.metadata_url,
                    "mcp_url": provisional.get("url", ""),
                }
            if client is None:
                return {"ok": False, "error": fix_err}
            provisional = final_provisional
        else:
            try:
                # One-shot probe during setup — not pooled; caller closes it below.
                client = _client_for(provisional, pooled=False)
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
        # On edit, the id is fixed at creation time — re-deriving from name would
        # orphan the old record and create a duplicate the next time the user saved.
        if edit_id:
            skill_id = edit_id
        else:
            base_id = "mcp-" + _slugify(name)
            existing_ids = {c["id"] for c in _load_connections()}
            skill_id = base_id
            suffix = 2
            while skill_id in existing_ids:
                skill_id = f"{base_id}-{suffix}"
                suffix += 1

        try:
            raw_tools = client.list_tools()
        except Exception as e:
            return {"ok": False, "error": f"Could not list tools: {e}"}

        if not raw_tools:
            return {"ok": False, "error": "This server returned no tools"}

        # Block save if probe detects header-gated auth — otherwise we'd persist
        # a connection where tools/list works but every real call fails (Nabu).
        auth_failed, probe_detail = _probe_tools_for_auth(
            client, raw_tools, provisional.get("transport", "http")
        )
        if auth_failed:
            _log.debug("[save probe] auth failure: %s", probe_detail[:120])
            return {
                "ok": False,
                "error": _auth_failure_message(provisional),
                "auth_probe_failed": True,
                "probe_detail": probe_detail,
                "tool_count": len(raw_tools),
            }
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
        if provisional.get("oauth_provider_id"):
            conn["oauth_provider_id"] = provisional["oauth_provider_id"]

    with _MUTATION_LOCK:
        # Second _load_connections() inside the lock is intentional — another
        # thread may have written config between the id-collision check above
        # (line ~564, outside the lock) and this write. Re-reading here is the
        # standard load-modify-save pattern under a mutex; removing this read
        # would introduce a TOCTOU race that silently drops concurrent saves.
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
        removed = next((c for c in connections if c["id"] == connection_id), None)
        updated = [c for c in connections if c["id"] != connection_id]
        if len(updated) == len(connections):
            return {"ok": False, "error": "Connection not found"}
        _save_connections(updated)
        _unregister(connection_id)
    # Terminate the pooled stdio process (if any) outside the mutation lock.
    if removed and removed.get("transport") == "stdio":
        release_from_pool({
            "command": removed.get("command", ""),
            "args": removed.get("args", []),
            "env": removed.get("env", {}),
            "name": removed.get("name", ""),
        })
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
        # Intentionally uses server_info() rather than a lightweight ping.
        # A bare HEAD/ping would return 200 for auth-gated servers too
        # (door opens but callers get a 401 once inside). server_info goes
        # one handshake deeper and catches that class of failure at health-
        # check time rather than at first real tool call.
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


def _mask_secret(s: str) -> str:
    """Return a masked preview safe to render — never leak full secrets to the UI."""
    if not s:
        return ""
    if len(s) <= 4:
        return "•" * len(s)
    return "•" * 8 + s[-4:]


def _auth_value_hint(auth_type: str, auth_value: str) -> str:
    """Build a non-secret hint the edit form can show as a placeholder.

    For 'basic' (email:token) we keep the email visible and mask only the token —
    the email isn't a credential and pre-filling it saves the user from re-typing.
    """
    if not auth_value:
        return ""
    if auth_type == "basic" and ":" in auth_value:
        email, token = auth_value.split(":", 1)
        return f"{email}:{_mask_secret(token)}"
    return _mask_secret(auth_value)


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
            # Env values may contain tokens — expose key names + masked values only.
            env = conn.get("env") or {}
            row["env_hint"] = {k: _mask_secret(str(v)) for k, v in env.items()}
        else:
            row["url"] = conn.get("url", "")
            row["auth_type"] = conn.get("auth_type", "none")
            row["auth_value_hint"] = _auth_value_hint(
                conn.get("auth_type", "none"), conn.get("auth_value", "")
            )
            headers = conn.get("extra_headers") or {}
            row["extra_headers_hint"] = {k: _mask_secret(str(v)) for k, v in headers.items()}
            if conn.get("oauth_provider_id"):
                row["oauth_provider_id"] = conn["oauth_provider_id"]
        out.append(row)
    return out
