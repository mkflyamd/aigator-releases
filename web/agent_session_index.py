"""Persistent index of agent session files for the History panel.

One row per transcript file, keyed by path with the mtime and size it was parsed
at, so a refresh only re-parses files that changed and drops rows for files that
are gone. Lives in ~/.gator in WAL mode; a corrupt file or a different schema
version is deleted and rebuilt from the transcripts.
"""
from __future__ import annotations

import contextlib
import sqlite3
import threading
from pathlib import Path

VERSION = 1
INDEX_PATH = Path.home() / ".gator" / "agent-session-index.db"

_SCHEMA = """
CREATE TABLE IF NOT EXISTS sessions (
    path TEXT PRIMARY KEY,
    unit TEXT NOT NULL,
    home TEXT NOT NULL,
    source TEXT NOT NULL,
    agent TEXT NOT NULL,
    session_id TEXT NOT NULL,
    cwd TEXT NOT NULL,
    cwd_key TEXT NOT NULL,
    title TEXT NOT NULL,
    branch TEXT NOT NULL,
    started_at REAL NOT NULL,
    last_active_at REAL NOT NULL,
    mtime_ns INTEGER NOT NULL,
    size INTEGER NOT NULL,
    preview TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS sessions_unit ON sessions(unit);
CREATE INDEX IF NOT EXISTS sessions_source_agent ON sessions(source, agent);
"""
_LIST_COLUMNS = "path, home, source, session_id, cwd, cwd_key, title, branch, started_at, last_active_at"
_WRITE_LOCK = threading.Lock()
_MAX_KEYS = 500  # SQLite caps bound parameters; past this the caller's own filter does the work


class _WrongVersion(sqlite3.DatabaseError):
    pass


def _open() -> sqlite3.Connection:
    INDEX_PATH.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(INDEX_PATH, timeout=10)
    try:
        if con.execute("PRAGMA user_version").fetchone()[0] not in (0, VERSION):
            raise _WrongVersion("agent session index has another schema version")
        con.execute("PRAGMA journal_mode=WAL")
        con.execute("PRAGMA synchronous=NORMAL")
        con.executescript(_SCHEMA)
        con.execute(f"PRAGMA user_version={VERSION}")
        return con
    except BaseException:
        con.close()
        raise


def _discard() -> None:
    for suffix in ("", "-wal", "-shm"):
        with contextlib.suppress(OSError):
            Path(f"{INDEX_PATH}{suffix}").unlink()


def _corrupt(exc: sqlite3.Error) -> bool:
    return isinstance(exc, sqlite3.DatabaseError) and not isinstance(exc, sqlite3.OperationalError)


@contextlib.contextmanager
def _db():
    """A connection to the index. A corrupt or wrong-version file is deleted so the
    next refresh rebuilds it; a busy database is only retried by the next call."""
    try:
        con = _open()
    except sqlite3.Error as exc:
        if not _corrupt(exc):
            raise
        _discard()
        con = _open()
    try:
        with con:
            yield con
    except sqlite3.Error as exc:
        if _corrupt(exc):
            _discard()
        raise
    finally:
        con.close()


def known(unit: str) -> dict[str, tuple[int, int]]:
    with _db() as con:
        return {p: (m, s) for p, m, s in con.execute("SELECT path, mtime_ns, size FROM sessions WHERE unit = ?", (unit,))}


def populated() -> set[str]:
    with _db() as con:
        return {u for (u,) in con.execute("SELECT DISTINCT unit FROM sessions")}


def apply(rows: list[dict], removed: list[str]) -> None:
    """Upsert parsed rows and delete rows for vanished files in one transaction."""
    with _WRITE_LOCK, _db() as con:
        con.executemany("DELETE FROM sessions WHERE path = ?", [(p,) for p in removed])
        con.executemany(
            "INSERT OR REPLACE INTO sessions (path, unit, home, source, agent, session_id, cwd, cwd_key, title, branch, "
            "started_at, last_active_at, mtime_ns, size, preview) VALUES (:path, :unit, :home, :source, :agent, "
            ":session_id, :cwd, :cwd_key, :title, :branch, :started_at, :last_active_at, :mtime_ns, :size, :preview)",
            rows,
        )


def rows(
    source: str, agent: str, cwd_keys: list[str], *, session_id: str | None = None, with_preview: bool = False
) -> list[dict]:
    """Session rows of one agent in one source whose folder is one of cwd_keys, newest
    first. Files that are not user sessions are kept in the table (agent '') so they
    are not parsed again."""
    cols = _LIST_COLUMNS + (", preview" if with_preview else "")
    sql = f"SELECT {cols} FROM sessions WHERE source = ? AND agent = ?"
    args: list = [source, agent]
    if len(cwd_keys) <= _MAX_KEYS:
        sql += f" AND cwd_key IN ({','.join('?' * len(cwd_keys))})"
        args += cwd_keys
    if session_id is not None:
        sql += " AND session_id = ?"
        args.append(session_id)
    with _db() as con:
        cur = con.execute(sql + " ORDER BY last_active_at DESC", args)
        names = [d[0] for d in cur.description]
        return [dict(zip(names, r)) for r in cur.fetchall()]
