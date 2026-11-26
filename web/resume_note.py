"""Tell the next turn where the previous one stopped, so "continue" does not start over.

Only a turn that left something open gets a note: it was cut off, or it proposed a host
command whose result was never read. A turn that finished needs none.
"""

from __future__ import annotations

import json
import re

from conversation_store import INTERRUPTED_MSG

_MAX_TOOLS_LISTED = 6
_REQUEST_ID = re.compile(r'"request_id"\s*:\s*"([^"]+)"')


def _text_of(content) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return " ".join(b.get("text", "") for b in content if isinstance(b, dict) and b.get("type") == "text")
    return ""


def _is_request(msg: dict) -> bool:
    return msg.get("role") == "user" and bool(_text_of(msg.get("content")).strip())


def _calls(msg: dict):
    """(id, name, input) for each tool call in an assistant message, either wire format."""
    if msg.get("role") != "assistant":
        return
    for b in (msg.get("content") if isinstance(msg.get("content"), list) else []):
        if isinstance(b, dict) and b.get("type") == "tool_use":
            yield b.get("id"), b.get("name"), b.get("input") or {}
    for tc in (msg.get("tool_calls") if isinstance(msg.get("tool_calls"), list) else []):
        fn = tc.get("function") or {}
        try:
            args = json.loads(fn.get("arguments") or "{}")
        except ValueError:
            args = {}
        yield tc.get("id"), fn.get("name"), args


def _results(msg: dict):
    """(tool_use_id, content as text) for each tool result in a message, either wire format."""
    if msg.get("role") == "tool":
        yield msg.get("tool_call_id"), str(msg.get("content") or "")
    for b in (msg.get("content") if isinstance(msg.get("content"), list) else []):
        if isinstance(b, dict) and b.get("type") == "tool_result":
            c = b.get("content")
            yield b.get("tool_use_id"), c if isinstance(c, str) else _text_of(c)


def _failed(result: str) -> bool:
    try:
        data = json.loads(result)
    except ValueError:
        return False
    return isinstance(data, dict) and bool(data.get("error"))


def resume_note(history: list[dict]) -> str:
    """A short system-prompt block for a turn that follows an unfinished one, else ""."""
    start = max((i for i, m in enumerate(history) if _is_request(m)), default=None)
    if start is None:
        return ""
    turn = history[start:]
    request = _text_of(turn[0].get("content")).strip()

    names: dict = {}
    outcomes: list[str] = []
    read_ids: set[str] = set()
    proposed: list[str] = []
    for msg in turn[1:]:
        for cid, name, args in _calls(msg):
            names[cid] = name
            if name == "host_command_result" and args.get("request_id"):
                read_ids.add(str(args["request_id"]))
        for cid, result in _results(msg):
            name = names.get(cid)
            if not name:
                continue
            outcomes.append(f"{name}: {'failed' if _failed(result) else 'ok'}")
            if name == "run_on_host":
                found = _REQUEST_ID.search(result)
                if found:
                    proposed.append(found.group(1))

    unread = [rid for rid in proposed if rid not in read_ids]
    interrupted = INTERRUPTED_MSG in _text_of(turn[-1].get("content"))
    if not unread and not interrupted:
        return ""

    lines = ["[Where the previous turn stopped]", f'The user\'s last request was: "{request[:300]}"']
    if outcomes:
        lines.append("Tools it ran: " + "; ".join(outcomes[-_MAX_TOOLS_LISTED:]) + ".")
    if interrupted:
        lines.append("It was cut off before it finished. Continue from the results above instead of starting over.")
    for rid in unread:
        lines.append(
            f"run_on_host request {rid} was proposed and its result has not been read. Call host_command_result "
            "with that request_id before proposing another command."
        )
    return "\n\n" + "\n".join(lines)
