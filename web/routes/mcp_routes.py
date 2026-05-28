"""MCP connection management routes."""
import dataclasses
import logging
from typing import Literal

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

logger = logging.getLogger(__name__)

from mcp.manager import add_or_update, remove, health_check, list_with_status
from mcp.normalizer import normalize, NormalizeResult
from mcp.github_fetcher import github_fetcher as _real_fetcher

router = APIRouter()


class MCPConnectionRequest(BaseModel):
    transport: Literal["http", "stdio"] = "http"
    # http fields
    url: str = ""
    auth_type: str = "none"   # none | bearer | api_key
    auth_value: str = ""
    headers: dict[str, str] = {}
    # stdio fields
    command: str = ""
    args: list[str] = []
    env: dict[str, str] = {}
    # common
    name: str = ""            # empty = auto-detect from server


@router.get("/api/config/mcp")
def list_connections():
    return {"connections": list_with_status()}


@router.post("/api/config/mcp")
def add_connection(req: MCPConnectionRequest):
    logger.info("save transport=%s name=%r url=%r command=%r args=%r",
                req.transport, req.name, req.url, req.command, req.args)
    if req.transport == "stdio":
        if not req.command.strip():
            raise HTTPException(status_code=400, detail="command is required for stdio transport")
    else:
        if not req.url.strip():
            raise HTTPException(status_code=400, detail="URL is required")
        if req.auth_type in ("bearer", "api_key") and not req.auth_value.strip():
            raise HTTPException(status_code=400, detail="Token/key is required for this auth type")
    result = add_or_update(req.model_dump())
    if not result.get("ok"):
        logger.warning("add_or_update failed url=%r cmd=%r: %s",
                       req.url or None, req.command or None, result.get("error"))
        raise HTTPException(status_code=400, detail=result.get("error", "Failed to connect"))
    logger.info("save ok name=%r tool_count=%s", result.get("name"), result.get("tool_count"))
    return result


@router.delete("/api/config/mcp/{connection_id}")
def delete_connection(connection_id: str):
    result = remove(connection_id)
    if not result.get("ok"):
        raise HTTPException(status_code=404, detail=result.get("error", "Not found"))
    return result


@router.post("/api/config/mcp/{connection_id}/health")
def connection_health(connection_id: str):
    return health_check(connection_id)


# ── Dependency helpers (injectable for tests) ─────────────────────────────────

def _get_fetcher():
    """Return the production GitHub fetcher. Tests monkeypatch this."""
    from mcp.normalizer import GITHUB_FETCH_ENABLED
    return _real_fetcher if GITHUB_FETCH_ENABLED else None


def _get_llm():
    """Return a lazy wrapper that builds the gateway LLM callable only when invoked."""
    from mcp.normalizer import LLM_FALLBACK_ENABLED
    if not LLM_FALLBACK_ENABLED:
        return None

    def _lazy_llm(prompt: str) -> str:
        from mcp.normalizer import _make_gateway_llm
        return _make_gateway_llm()(prompt)

    return _lazy_llm


# ── Analyze endpoint ──────────────────────────────────────────────────────────

class _AnalyzeRequest(BaseModel):
    raw_input: str


@router.post("/api/config/mcp/analyze")
def analyze_mcp(req: _AnalyzeRequest):
    """Analyze raw input and return a NormalizeResult. Read-only — no side effects."""
    result = normalize(
        req.raw_input,
        fetcher=_get_fetcher(),
        llm=_get_llm(),
    )
    # Build dict manually to handle all_results (which may contain NormalizeResult instances)
    # For nested results in all_results, don't include their all_results to avoid cycles
    def normalize_result_to_dict(nr: NormalizeResult, include_nested: bool = True) -> dict:
        return {
            "ok": nr.ok,
            "transport": nr.transport,
            "name": nr.name,
            "url": nr.url,
            "auth_type": nr.auth_type,
            "auth_value": nr.auth_value,
            "headers": nr.headers,
            "command": nr.command,
            "args": nr.args,
            "env": nr.env,
            "source": nr.source,
            "confidence": nr.confidence,
            "all_results": [normalize_result_to_dict(r, include_nested=False) for r in nr.all_results] if include_nested else [],
            "prerequisite_warning": nr.prerequisite_warning,
            "error": nr.error,
        }
    d = normalize_result_to_dict(result)
    logger.info("analyze ok=%s transport=%s source=%s name=%r url=%r command=%r",
                d["ok"], d["transport"], d["source"], d["name"], d["url"], d["command"])
    return d
