"""Structured description of rejected tool calls, shared by both agent loops."""
from __future__ import annotations

import json

REJECTED_ERRORS = ("missing_required_params", "invalid_tool_input")


def _fields(result: dict) -> list[str]:
    if result.get("error") == "missing_required_params":
        return [str(f) for f in result.get("missing") or []]
    field = result.get("field")
    return [str(field)] if field else []


def rejection_summaries(tool_calls: list, results: list) -> list[dict]:
    """One {"tool", "fields"} entry per failed call in a round (names from the tool's own result)."""
    out = []
    for tc, result in zip(tool_calls, results):
        if not (isinstance(result, dict) and result.get("error")):
            continue
        out.append({"tool": str(result.get("tool") or tc.name), "fields": _fields(result)})
    return out


def rejection_summary_text(result: dict) -> str | None:
    """One-line tool_result summary for a rejected call, or None for any other result."""
    if not (isinstance(result, dict) and result.get("error") in REJECTED_ERRORS):
        return None
    fields = ", ".join(_fields(result))
    label = "missing" if result["error"] == "missing_required_params" else "invalid"
    return f"Rejected {result.get('tool', 'tool')}: {label} {fields}".strip()


def stalled_chunk(summaries: list[dict]) -> str:
    """SSE `stalled` event naming the failed tool(s) and fields; `retry_note` feeds Continue."""
    parts = [
        f"{s['tool']} ({', '.join(s['fields'])})" if s["fields"] else s["tool"]
        for s in summaries
    ]
    names = "; ".join(parts) or "tool"
    payload = {
        "stalled": True,
        "message": f"Gator could not form a valid call to {names} after one repair attempt "
                   "— click Continue to retry.",
        "failed_calls": summaries,
        "retry_note": f"Note: the previous attempt failed because the call to {names} had "
                      "missing or invalid arguments. Supply every required argument this time.",
    }
    return f"data: {json.dumps(payload)}\n\n"
