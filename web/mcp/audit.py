"""Fail-open execution telemetry for MCP transport calls."""
from __future__ import annotations

import re
import time


def _audit_name(cfg: dict, tool: str) -> str:
    connection = str(cfg.get("id") or cfg.get("name") or "mcp")
    slug = re.sub(r"[^a-z0-9]+", "-", connection.lower()).strip("-") or "mcp"
    if not slug.startswith("mcp-"):
        slug = f"mcp-{slug}"
    return f"{slug}__{tool}"


def schedule_mcp_call(
    cfg: dict, tool: str, outcome: str, started_at: float, error_code: str | None = None,
) -> None:
    """Schedule one MCP call record without delaying or altering the call."""
    try:
        import turn_telemetry

        if turn_telemetry.mcp_audit_suppressed.get():
            return
        turn_telemetry.schedule_tool_call(
            _audit_name(cfg, tool), outcome,
            round((time.perf_counter() - started_at) * 1000),
            error_code=error_code,
        )
    except Exception:
        pass
