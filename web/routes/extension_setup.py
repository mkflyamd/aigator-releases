"""Agentic setup wizard endpoints.

⚠️  POST-MVP — DO NOT MODIFY FOR MVP WORK ⚠️

These endpoints back the deferred agentic setup wizard
(web/static/extension_setup_modal.js). The supported MVP "Add MCP" path is
the legacy form modal at web/static/mcp_add_modal.js, backed by
web/routes/mcp_routes.py. Bug fixes for MCP add/edit/test belong in
mcp_routes.py — NOT here. Only touch this file (and web/extensions/*) if
the user has explicitly asked for post-MVP wizard work.
"""
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from extensions.registry import get_adapter
from extensions.prompts.loader import load_prompt
from extensions import tools as ext_tools

router = APIRouter()


class StartRequest(BaseModel):
    extension_type: str
    raw_input: str | None = None


class CommitRequest(BaseModel):
    session_id: str


@router.post("/api/extensions/setup/start")
def start(req: StartRequest):
    try:
        adapter = get_adapter(req.extension_type)
    except KeyError:
        raise HTTPException(status_code=400,
                            detail=f"Unknown extension_type {req.extension_type!r}")
    initial: dict = {}
    if req.raw_input:
        initial = adapter.normalize(req.raw_input) or {}
        if req.raw_input.startswith(("http://", "https://")):
            # Always merge provider-specific hints from prefill; they override
            # generic normalizer defaults (e.g. auth_type=none) for known hosts.
            prefill = adapter.prefill_from_url(req.raw_input)
            if prefill:
                merged = dict(prefill)
                merged.update(initial)          # normalizer wins for everything else
                # But let prefill's auth_type override normalizer's 'none' default
                if initial.get("auth_type") in (None, "none") and "auth_type" in prefill:
                    merged["auth_type"] = prefill["auth_type"]
                # Let prefill's name override normalizer's generic URL-derived name
                # for known providers.  mcp.normalizer builds the name from the
                # last URL path segment, so URLs ending in "/mcp" (the de-facto
                # MCP path convention, e.g. ".../v1/mcp") always yield "mcp" —
                # the only generic value we need to guard against here.
                if "name" in prefill and initial.get("name") in (None, "", "mcp"):
                    merged["name"] = prefill["name"]
                initial = merged
    # Ensure transport always has a default so visibility conditions work on first render
    if req.extension_type == "mcp" and not initial.get("transport"):
        initial.setdefault("transport", "http")
    sid = ext_tools._SESSIONS.create(req.extension_type, initial=initial)
    return {
        "session_id": sid,
        "system_prompt": load_prompt(req.extension_type),
        "initial_field_state": initial,
        "raw_input": req.raw_input,
        "config_schema": adapter.config_schema,
    }


@router.post("/api/extensions/setup/normalize")
def normalize(req: StartRequest):
    """Detect fields from raw input without creating a session. Used by the form detect button."""
    try:
        adapter = get_adapter(req.extension_type)
    except KeyError:
        raise HTTPException(status_code=400, detail=f"Unknown extension_type {req.extension_type!r}")
    if not req.raw_input or not req.raw_input.strip():
        raise HTTPException(status_code=422, detail="raw_input is required")

    initial: dict = adapter.normalize(req.raw_input) or {}
    if req.raw_input.strip().startswith(("http://", "https://")):
        prefill = adapter.prefill_from_url(req.raw_input.strip())
        if prefill:
            merged = dict(prefill)
            merged.update(initial)
            if initial.get("auth_type") in (None, "none") and "auth_type" in prefill:
                merged["auth_type"] = prefill["auth_type"]
            if "name" in prefill and initial.get("name") in (None, "", "mcp"):
                merged["name"] = prefill["name"]
            initial = merged
    if req.extension_type == "mcp" and not initial.get("transport"):
        initial.setdefault("transport", "http")

    ok = bool(initial.get("url") or initial.get("command"))
    return {"ok": ok, "fields": initial}


@router.get("/api/extensions/setup/events/{session_id}")
def events(session_id: str):
    try:
        evs = ext_tools._SESSIONS.drain_events(session_id)
    except KeyError:
        raise HTTPException(status_code=404, detail="Session not found")
    return {"events": evs}


@router.get("/api/extensions/setup/draft/{session_id}")
def draft(session_id: str):
    try:
        return {"draft": ext_tools._SESSIONS.get(session_id)}
    except KeyError:
        raise HTTPException(status_code=404, detail="Session not found")


class PatchDraftRequest(BaseModel):
    fields: dict


@router.patch("/api/extensions/setup/draft/{session_id}")
def patch_draft(session_id: str, req: PatchDraftRequest):
    """Merge fields into the session draft (used by the form detect flow)."""
    try:
        current = ext_tools._SESSIONS.get(session_id)
    except KeyError:
        raise HTTPException(status_code=404, detail="Session not found")
    clean = {k: v for k, v in req.fields.items() if not k.startswith("_")}
    ext_tools._SESSIONS.merge(session_id, clean)
    return {"ok": True}


@router.post("/api/extensions/setup/test")
def test_connection(req: CommitRequest):
    try:
        draft_cfg = ext_tools._SESSIONS.get(req.session_id)
        ext_type = ext_tools._SESSIONS.extension_type(req.session_id)
    except KeyError:
        raise HTTPException(status_code=404, detail="Session not found")
    adapter = get_adapter(ext_type)
    result = adapter.test_connection(draft_cfg)
    ext_tools._SESSIONS.emit(req.session_id, {
        "type": "test_result", "ok": result.ok,
        "detail": result.detail, "tool_count": result.tool_count,
        "raw": result.raw or {},
    })
    if result.highlight_field:
        ext_tools._SESSIONS.emit(req.session_id, {
            "type": "highlight", "field_path": result.highlight_field,
        })
    return {"ok": result.ok, "detail": result.detail, "tool_count": result.tool_count}


@router.post("/api/extensions/setup/commit")
def commit(req: CommitRequest):
    try:
        draft_cfg = ext_tools._SESSIONS.get(req.session_id)
        ext_type = ext_tools._SESSIONS.extension_type(req.session_id)
    except KeyError:
        raise HTTPException(status_code=404, detail="Session not found")
    adapter = get_adapter(ext_type)

    # Always probe before committing — catches servers that allow tools/list
    # without auth but reject real tool calls (e.g. header-gated APIs like Nabu).
    test = adapter.test_connection(draft_cfg)
    if not test.ok:
        # Emit events so the wizard UI updates (pill + field highlight)
        ext_tools._SESSIONS.emit(req.session_id, {
            "type": "test_result", "ok": False, "detail": test.detail,
            "tool_count": test.tool_count, "raw": test.raw,
        })
        if test.highlight_field:
            ext_tools._SESSIONS.emit(req.session_id, {
                "type": "highlight", "field_path": test.highlight_field,
            })
        raise HTTPException(status_code=422, detail={
            "message": test.detail,
            "auth_required": bool(test.highlight_field),
        })

    result = adapter.install(draft_cfg)
    if not result.ok:
        raise HTTPException(status_code=400, detail=result.error)
    ext_tools._SESSIONS.discard(req.session_id)
    return {"ok": True, "connection_id": result.connection_id, "name": result.name}


@router.delete("/api/extensions/setup/{session_id}")
def discard(session_id: str):
    ext_tools._SESSIONS.discard(session_id)
    return {"ok": True}
