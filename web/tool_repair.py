"""Structured description of rejected tool calls, shared by both agent loops."""
from __future__ import annotations

import json
import re

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


_LEAKED_CALL = re.compile(r"<\s*[|｜]\s*(?:DSML|tool[▁_ ]?calls?)", re.IGNORECASE)

LEAKED_CALL_NOTE = (
    "Your last reply wrote a tool call as plain text, so nothing ran. Call the tool through "
    "the function-calling interface, not as text, and continue the user's original request."
)


def leaked_tool_call(text: str) -> bool:
    """True when a model wrote its native tool-call markup into the message text."""
    return bool(_LEAKED_CALL.search(text or ""))


def leaked_call_stalled_chunk() -> str:
    """SSE `stalled` event for a model that wrote a tool call as text twice in a row."""
    payload = {
        "stalled": True,
        "message": "The model wrote a tool call as text instead of running it, even after one "
                   "retry — click Continue to try again, or switch models.",
        "retry_note": LEAKED_CALL_NOTE,
    }
    return f"data: {json.dumps(payload)}\n\n"
