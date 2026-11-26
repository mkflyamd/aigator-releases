"""History readers for agents that keep their sessions in a SQLite database.

Each scanner returns raw session records for one project folder; agent_sessions
adds the agent id, source and a clean title. Databases are opened read-only, so
reading never disturbs a running agent.
"""
from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Callable

SCAN_LIMIT = 300
_BUSY_TIMEOUT_SECONDS = 2


def _open(path: Path) -> sqlite3.Connection:
    return sqlite3.connect(f"{path.as_uri()}?mode=ro", uri=True, timeout=_BUSY_TIMEOUT_SECONDS)


def _text_parts(parts) -> str:
    """Joined text of one Crush message's parts, ignoring tool calls, results and pasted files."""
    try:
        items = json.loads(parts)
    except (TypeError, ValueError):
        return ""
    texts = []
    for p in items if isinstance(items, list) else ():
        data = p.get("data") if isinstance(p, dict) and p.get("type") == "text" else None
        if isinstance(data, dict) and isinstance(data.get("text"), str):
            texts.append(data["text"])
    return "\n".join(texts).strip()


def _crush_db(cwd: str) -> Path:
    return Path(cwd) / ".crush" / "crush.db"


def scan_crush(home: Path, cwd: str, same_dir: Callable[[str, str], bool]) -> list[dict]:
    """Crush keeps one database per project folder, so the folder is the match."""
    db = _crush_db(cwd)
    if not db.is_file():
        return []
    try:
        with _open(db) as con:
            rows = con.execute(
                "SELECT id, title, created_at, updated_at FROM sessions "
                "WHERE parent_session_id IS NULL AND message_count > 0 "
                "ORDER BY updated_at DESC LIMIT ?",
                (SCAN_LIMIT,),
            ).fetchall()
            out = []
            for sid, title, created, updated in rows:
                if not (title or "").strip() or title == "New Session":
                    first = con.execute(
                        "SELECT parts FROM messages WHERE session_id = ? AND role = 'user' "
                        "ORDER BY created_at LIMIT 1",
                        (sid,),
                    ).fetchone()
                    title = _text_parts(first[0]) if first else ""
                out.append(_record(sid, title, created, updated, db, cwd, 1))
    except (sqlite3.Error, OSError):
        return []
    return out


def _opencode_db(home: Path) -> Path:
    return home / ".local" / "share" / "opencode" / "opencode.db"


def scan_opencode(home: Path, cwd: str, same_dir: Callable[[str, str], bool]) -> list[dict]:
    """OpenCode keeps every project in one database; a session's folder is its directory column."""
    db = _opencode_db(home)
    if not db.is_file():
        return []
    try:
        with _open(db) as con:
            rows = con.execute(
                "SELECT id, directory, title, time_created, time_updated FROM session "
                "WHERE parent_id IS NULL AND time_archived IS NULL "
                "ORDER BY time_updated DESC LIMIT 2000",
            ).fetchall()
            out = []
            for sid, directory, title, created, updated in rows:
                if not same_dir(directory or "", cwd):
                    continue
                if not con.execute("SELECT 1 FROM message WHERE session_id = ? LIMIT 1", (sid,)).fetchone():
                    continue
                if not (title or "").strip() or title.startswith("New session - "):
                    title = _opencode_first_user_text(con, sid)
                out.append(_record(sid, title, created, updated, db, cwd, 1000))
                if len(out) >= SCAN_LIMIT:
                    break
    except (sqlite3.Error, OSError):
        return []
    return out


def _opencode_first_user_text(con: sqlite3.Connection, session_id: str) -> str:
    row = con.execute(
        "SELECT json_extract(p.data, '$.text') FROM part p JOIN message m ON m.id = p.message_id "
        "WHERE p.session_id = ? AND json_extract(m.data, '$.role') = 'user' "
        "AND json_extract(p.data, '$.type') = 'text' ORDER BY p.time_created LIMIT 1",
        (session_id,),
    ).fetchone()
    return row[0] if row and isinstance(row[0], str) else ""


def _record(sid: str, title: str, created, updated, db: Path, cwd: str, per_second: int) -> dict:
    return {
        "id": sid,
        "title": title or "",
        "branch": "",
        "started_at": float(created) / per_second,
        "last_active_at": float(updated) / per_second,
        "state": "done",
        "path": str(db),
        "cwd": cwd,
    }


def preview_crush(db: Path, session_id: str, limit: int) -> list[tuple[str, str]]:
    with _open(db) as con:
        rows = con.execute(
            "SELECT role, parts FROM messages WHERE session_id = ? AND role IN ('user', 'assistant') "
            "ORDER BY created_at DESC LIMIT ?",
            (session_id, limit),
        ).fetchall()
    pairs = [(role, _text_parts(parts)) for role, parts in reversed(rows)]
    return [p for p in pairs if p[1]]


def preview_opencode(db: Path, session_id: str, limit: int) -> list[tuple[str, str]]:
    with _open(db) as con:
        messages = con.execute(
            "SELECT id, json_extract(data, '$.role') FROM message WHERE session_id = ? "
            "ORDER BY time_created DESC LIMIT ?",
            (session_id, limit),
        ).fetchall()
        pairs = []
        for mid, role in reversed(messages):
            if role not in ("user", "assistant"):
                continue
            texts = con.execute(
                "SELECT json_extract(data, '$.text') FROM part WHERE message_id = ? "
                "AND json_extract(data, '$.type') = 'text' ORDER BY id",
                (mid,),
            ).fetchall()
            text = "\n".join(t[0] for t in texts if isinstance(t[0], str)).strip()
            if text:
                pairs.append((role, text))
    return pairs


SCANNERS = {"crush": scan_crush, "opencode-bare": scan_opencode}
PREVIEWERS = {"crush": preview_crush, "opencode-bare": preview_opencode}
