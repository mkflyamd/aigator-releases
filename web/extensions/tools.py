"""Scoped tool dispatch for the agentic setup wizard."""
from __future__ import annotations

import logging

import shared
from .registry import get_adapter
from .sessions import SessionStore

_log = logging.getLogger(__name__)
_SESSIONS = SessionStore()


def tool_set_field(args: dict) -> dict:
    sid = args["session_id"]
    try:
        _SESSIONS.set(sid, args["field_path"], args["value"])
    except KeyError:
        return {"ok": False, "error": f"Unknown session: {sid}"}
    return {"ok": True}


def tool_get_field(args: dict) -> dict:
    sid = args["session_id"]
    try:
        draft = _SESSIONS.get(sid)
    except KeyError:
        return {"ok": False, "error": f"Unknown session: {sid}"}
    return {"value": draft.get(args["field_path"])}


def tool_highlight_field(args: dict) -> dict:
    sid = args["session_id"]
    try:
        _SESSIONS.emit(sid,
                       {"type": "highlight", "field_path": args["field_path"]})
    except KeyError:
        return {"ok": False, "error": f"Unknown session: {sid}"}
    return {"ok": True}


def tool_show_instruction_panel(args: dict) -> dict:
    sid = args["session_id"]
    try:
        _SESSIONS.emit(sid, {
            "type": "instructions", "title": args["title"], "steps": args["steps"],
        })
    except KeyError:
        return {"ok": False, "error": f"Unknown session: {sid}"}
    return {"ok": True}


def tool_normalize_input(args: dict) -> dict:
    sid = args["session_id"]
    try:
        ext_type = _SESSIONS.extension_type(sid)
    except KeyError:
        return {"ok": False, "error": f"Unknown session: {sid}"}
    adapter = get_adapter(ext_type)
    parsed = adapter.normalize(args["raw"]) or {}
    for k, v in parsed.items():
        _SESSIONS.set(sid, k, v)
    return {"ok": bool(parsed), "fields": parsed}


def tool_fetch_doc(args: dict) -> dict:
    """Fetch + summarise a doc URL via the LLM gateway."""
    import requests
    import anthropic
    from llm.gateway import gateway_headers, get_gateway_url
    try:
        resp = requests.get(args["url"], timeout=15)
        resp.raise_for_status()
        body = resp.text[:20000]
    except Exception as exc:
        return {"ok": False, "error": str(exc)}
    api_key = shared.cfg.get("api_key", "")
    client = anthropic.Anthropic(
        api_key=api_key,
        base_url=get_gateway_url(),
        default_headers=gateway_headers(api_key),
    )
    try:
        msg = client.messages.create(
            model=shared.cfg.get("model", "claude-opus-4-7"),
            max_tokens=1024,
            messages=[{"role": "user", "content":
                "Extract MCP setup steps from this page (URL, auth type, scopes, "
                f"how to get a token). Return concise bullets.\n\n{body}"}],
        )
        text = "".join(b.text for b in msg.content if hasattr(b, "text"))
        return {"ok": True, "summary": text}
    except Exception as exc:
        return {"ok": False, "error": f"Failed to summarize docs: {str(exc)}"}


def tool_test_connection(args: dict) -> dict:
    sid = args["session_id"]
    try:
        ext_type = _SESSIONS.extension_type(sid)
    except KeyError:
        return {"ok": False, "error": f"Unknown session: {sid}"}
    adapter = get_adapter(ext_type)
    draft = _SESSIONS.get(sid)
    result = adapter.test_connection(draft)
    _SESSIONS.emit(sid, {
        "type": "test_result", "ok": result.ok, "detail": result.detail,
        "tool_count": result.tool_count, "raw": result.raw,
    })
    if result.highlight_field:
        _SESSIONS.emit(sid, {"type": "highlight", "field_path": result.highlight_field})
    return {"ok": result.ok, "detail": result.detail, "tool_count": result.tool_count}


_MCP_OAUTH_PORTS = list(range(3200, 3210))
_MCP_OAUTH_REDIRECT_URIS = [f"http://127.0.0.1:{p}/callback" for p in _MCP_OAUTH_PORTS]


def tool_start_oauth_flow(args: dict) -> dict:
    from oauth import discover_and_register, start_flow
    sid = args["session_id"]
    try:
        provider = discover_and_register(
            args["url"],
            redirect_uris=_MCP_OAUTH_REDIRECT_URIS,
        )
        flow = start_flow(provider, port_candidates=_MCP_OAUTH_PORTS)
        _SESSIONS.set(sid, "oauth_provider_id", provider.id)
        _SESSIONS.set(sid, "auth_type", "oauth2")
        _SESSIONS.emit(sid, {
            "type": "oauth_started",
            "authorize_url": flow["authorize_url"],
            "state": flow["state"],
            "provider_id": provider.id,
        })
        return {"ok": True, "provider_id": provider.id}
    except Exception as exc:
        return {"ok": False, "error": str(exc)}


def tool_mark_done(args: dict) -> dict:
    sid = args["session_id"]
    try:
        _SESSIONS.emit(sid, {"type": "ready_to_commit"})
    except KeyError:
        return {"ok": False, "error": f"Unknown session: {sid}"}
    return {"ok": True}


TOOL_DEFS: list[dict] = [
    {"name": "extension_setup__set_field",
     "description": "Write a value to the wizard's left-pane form field.",
     "input_schema": {"type": "object",
                      "required": ["session_id", "field_path", "value"],
                      "properties": {"session_id": {"type": "string"},
                                     "field_path": {"type": "string"},
                                     "value": {}}}},
    {"name": "extension_setup__get_field",
     "description": "Read a value from the wizard draft.",
     "input_schema": {"type": "object",
                      "required": ["session_id", "field_path"],
                      "properties": {"session_id": {"type": "string"},
                                     "field_path": {"type": "string"}}}},
    {"name": "extension_setup__highlight_field",
     "description": "Visually pulse a form field to direct the user's eye.",
     "input_schema": {"type": "object",
                      "required": ["session_id", "field_path"],
                      "properties": {"session_id": {"type": "string"},
                                     "field_path": {"type": "string"}}}},
    {"name": "extension_setup__show_instruction_panel",
     "description": "Render a checklist of human steps in the left pane.",
     "input_schema": {"type": "object",
                      "required": ["session_id", "title", "steps"],
                      "properties": {"session_id": {"type": "string"},
                                     "title": {"type": "string"},
                                     "steps": {"type": "array",
                                               "items": {"type": "string"}}}}},
    {"name": "extension_setup__normalize_input",
     "description": "Parse user-pasted text/URL/JSON into form fields.",
     "input_schema": {"type": "object",
                      "required": ["session_id", "raw"],
                      "properties": {"session_id": {"type": "string"},
                                     "raw": {"type": "string"}}}},
    {"name": "extension_setup__fetch_doc",
     "description": "Fetch a documentation URL and summarise the setup steps.",
     "input_schema": {"type": "object", "required": ["url"],
                      "properties": {"url": {"type": "string"}}}},
    {"name": "extension_setup__test_connection",
     "description": "Test the current draft against the live endpoint.",
     "input_schema": {"type": "object", "required": ["session_id"],
                      "properties": {"session_id": {"type": "string"}}}},
    {"name": "extension_setup__start_oauth_flow",
     "description": "Begin OAuth for the current URL; opens a browser popup.",
     "input_schema": {"type": "object",
                      "required": ["session_id", "url"],
                      "properties": {"session_id": {"type": "string"},
                                     "url": {"type": "string"}}}},
    {"name": "extension_setup__mark_done",
     "description": "Signal that the draft is ready to commit.",
     "input_schema": {"type": "object", "required": ["session_id"],
                      "properties": {"session_id": {"type": "string"}}}},
]


def register() -> None:
    handlers = {
        "extension_setup__set_field":              tool_set_field,
        "extension_setup__get_field":              tool_get_field,
        "extension_setup__highlight_field":        tool_highlight_field,
        "extension_setup__show_instruction_panel": tool_show_instruction_panel,
        "extension_setup__normalize_input":        tool_normalize_input,
        "extension_setup__fetch_doc":              tool_fetch_doc,
        "extension_setup__test_connection":        tool_test_connection,
        "extension_setup__start_oauth_flow":       tool_start_oauth_flow,
        "extension_setup__mark_done":              tool_mark_done,
    }
    existing_names = {t["name"] for t in shared.TOOLS}
    for d in TOOL_DEFS:
        if d["name"] not in existing_names:
            shared.TOOLS.append(d)
        shared.TOOL_DISPATCH[d["name"]] = handlers[d["name"]]
    shared.SKILL_TOOLS_MAP["_extension_setup"] = set(handlers.keys())
    _log.info("extension_setup: registered %d tools", len(handlers))
