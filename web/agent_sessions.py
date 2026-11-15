"""Project-scoped agent session history, read from the agents' own transcript files.

Nothing is stored: each call reads the head and tail of transcript files that
Claude Code and Codex already keep, and caches the parsed result by
(path, mtime, size).
"""
from __future__ import annotations

import json
import os
import re
from datetime import datetime
from pathlib import Path

import agent_handoff as ah

HEAD_BYTES = 256 * 1024
TAIL_BYTES = 256 * 1024
TITLE_MAX = 120
SESSION_ID_RE = re.compile(r"^[A-Za-z0-9._-]{1,80}$")

_REMINDER = re.compile(r"<system-reminder>.*?</system-reminder>", re.S)
_SKIP_PREFIXES = (
    "<command-name>",
    "<command-message>",
    "<command-args>",
    "<local-command",
    "Caveat:",
    "[Request interrupted",
    "<user-prompt-submit-hook>",
    "<ide_",
    "<task-notification",
)


def real_user_text(text: str) -> str:
    """The user's own words on one line, or "" for injected boilerplate."""
    t = _REMINDER.sub("", text or "").strip()
    if not t or t.startswith(_SKIP_PREFIXES):
        return ""
    return " ".join(t.split())


def _clip(text: str) -> str:
    t = " ".join((text or "").split())
    return t if len(t) <= TITLE_MAX else t[: TITLE_MAX - 1].rstrip() + "…"


def _epoch(iso) -> float | None:
    if not isinstance(iso, str) or not iso:
        return None
    try:
        return datetime.fromisoformat(iso.replace("Z", "+00:00")).timestamp()
    except ValueError:
        return None


def _json_lines(raw: bytes, drop_first: bool, drop_last: bool) -> list[dict]:
    lines = raw.decode("utf-8", "replace").split("\n")
    if drop_first:
        lines = lines[1:]
    if drop_last:
        lines = lines[:-1]
    out = []
    for line in lines:
        line = line.strip()
        if not line:
            continue
        try:
            obj = json.loads(line)
        except ValueError:
            continue
        if isinstance(obj, dict):
            out.append(obj)
    return out


def _read_head(path: Path) -> list[dict]:
    with open(path, "rb") as fh:
        raw = fh.read(HEAD_BYTES + 1)
    return _json_lines(raw[:HEAD_BYTES], False, len(raw) > HEAD_BYTES)


def _read_tail(path: Path, size: int) -> list[dict]:
    start = max(0, size - TAIL_BYTES)
    with open(path, "rb") as fh:
        fh.seek(start)
        raw = fh.read()
    return _json_lines(raw, start > 0, False)


def _last_value(objs: list[dict], typ: str, field: str) -> str:
    for o in reversed(objs):
        v = o.get(field)
        if o.get("type") == typ and isinstance(v, str) and v.strip():
            return v.strip()
    return ""


def _claude_message(o: dict):
    """(role, one-line text) for a real user or assistant turn, else None."""
    if o.get("type") not in ("user", "assistant") or o.get("isMeta"):
        return None
    msg = o.get("message")
    content = msg.get("content") if isinstance(msg, dict) else None
    if isinstance(content, str):
        parts = [content]
    elif isinstance(content, list):
        parts = [
            b["text"]
            for b in content
            if isinstance(b, dict) and b.get("type") == "text" and isinstance(b.get("text"), str)
        ]
    else:
        return None
    text = "\n".join(parts)
    text = real_user_text(text) if o["type"] == "user" else " ".join(text.split())
    return (o["type"], text) if text else None


def _codex_message(o: dict):
    if o.get("type") != "response_item":
        return None
    p = o.get("payload")
    if not isinstance(p, dict) or p.get("type") != "message" or p.get("role") not in ("user", "assistant"):
        return None
    content = p.get("content")
    parts = [
        b["text"]
        for b in (content if isinstance(content, list) else [])
        if isinstance(b, dict) and isinstance(b.get("text"), str)
    ]
    text = "\n".join(parts)
    if p["role"] == "user":
        if text.lstrip().startswith(ah._CODEX_CONTEXT_PREFIXES):
            return None
        text = real_user_text(text)
    else:
        text = " ".join(text.split())
    return (p["role"], text) if text else None


def parse_claude(path: Path, st) -> dict | None:
    """A session record for one Claude transcript, or None when it is not a user session."""
    session_id = path.stem
    if not SESSION_ID_RE.match(session_id):
        return None
    head = _read_head(path)
    tail = _read_tail(path, st.st_size) if st.st_size > HEAD_BYTES else head
    meta = next((o for o in head if isinstance(o.get("cwd"), str)), None)
    if meta is None or meta.get("isSidechain"):
        return None
    entrypoint = next((str(o["entrypoint"]) for o in head if o.get("entrypoint")), "")
    if entrypoint.startswith("sdk"):
        return None
    first = ""
    for o in head:
        m = _claude_message(o)
        if m and m[0] == "user":
            first = m[1]
            break
    both = head + tail
    title = _last_value(both, "custom-title", "customTitle") or _last_value(both, "ai-title", "aiTitle") or first
    if not title:
        return None
    branch = next((o["gitBranch"] for o in reversed(both) if isinstance(o.get("gitBranch"), str) and o["gitBranch"]), "")
    started = next((t for t in (_epoch(o.get("timestamp")) for o in head) if t), None)
    return {
        "id": session_id,
        "agent": "claude",
        "title": _clip(title),
        "branch": branch,
        "started_at": started or st.st_mtime,
        "last_active_at": st.st_mtime,
        "state": "done",
        "path": str(path),
        "cwd": meta["cwd"],
    }


def codex_meta(path: Path) -> dict | None:
    """The first line's session_meta payload, read without loading the file."""
    try:
        with open(path, "rb") as fh:
            obj = json.loads(fh.readline(HEAD_BYTES))
    except (OSError, ValueError):
        return None
    if not isinstance(obj, dict) or obj.get("type") != "session_meta":
        return None
    payload = obj.get("payload")
    return payload if isinstance(payload, dict) else None


def parse_codex(path: Path, st) -> dict | None:
    """A session record for one Codex rollout, or None when it is not a user session."""
    meta = codex_meta(path)
    if meta is None:
        return None
    session_id = meta.get("id")
    cwd = meta.get("cwd")
    if not isinstance(session_id, str) or not SESSION_ID_RE.match(session_id) or not isinstance(cwd, str):
        return None
    source = meta.get("source")
    if isinstance(source, dict) and "subagent" in source:
        return None
    first = ""
    for o in _read_head(path):
        m = _codex_message(o)
        if m and m[0] == "user":
            first = m[1]
            break
    if not first:
        return None
    git = meta.get("git") if isinstance(meta.get("git"), dict) else {}
    branch = git.get("branch") if isinstance(git.get("branch"), str) else ""
    return {
        "id": session_id,
        "agent": "codex",
        "title": _clip(first),
        "branch": branch,
        "started_at": _epoch(meta.get("timestamp")) or st.st_mtime,
        "last_active_at": st.st_mtime,
        "state": "done",
        "path": str(path),
        "cwd": cwd,
    }
