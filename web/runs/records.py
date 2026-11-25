"""RunRecord: the one persisted record of a command or code run, and its sqlite mirror.

The database is a durable mirror only. Process handles and liveness live in memory
(runs/supervisor.py); nothing here is consulted to decide whether a process is alive.
"""
from __future__ import annotations

import json
import logging
import sqlite3
import threading
from dataclasses import asdict, dataclass, field, fields
from pathlib import Path

_log = logging.getLogger(__name__)

STATES = (
    "awaiting_approval", "preparing", "running", "finished", "timed_out", "cancelled", "denied",
    "policy_blocked", "expired", "failed_to_start", "interrupted", "abandoned",
)
ACTIVE_STATES = frozenset({"awaiting_approval", "preparing", "running"})
OUTPUT_TAIL_CHARS = 2000
_CRASH_VALUE_FLOOR = 0xC0000000


@dataclass
class RunRecord:
    id: str
    context_id: str
    path: str
    kind: str
    scope: str
    state: str
    turn_id: str = ""
    created_at: float = 0.0
    expires_at: float = 0.0
    setup_started_at: float = 0.0
    run_started_at: float = 0.0
    teardown_started_at: float = 0.0
    finished_at: float = 0.0
    exit: dict | None = None
    facts: dict = field(default_factory=dict)
    grant_ids: list = field(default_factory=list)
    probe_log: list = field(default_factory=list)
    reason: str = ""
    error: str = ""
    owner_pid: int = 0
    owner_create_time: float = 0.0
    output_tail: str = ""
    output_truncated: bool = False
    rev: int = 0

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict) -> "RunRecord":
        known = {f.name for f in fields(cls)}
        return cls(**{k: v for k, v in data.items() if k in known})


def exit_info(code) -> dict | None:
    """Exit code, its hex form, and whether it falls in the NTSTATUS error range. Facts only."""
    if code is None:
        return None
    unsigned = int(code) & 0xFFFFFFFF
    return {"code": int(code), "hex": f"0x{unsigned:08X}", "is_crash_value": unsigned >= _CRASH_VALUE_FLOOR}


def tail_of(text: str, limit: int) -> tuple[str, bool]:
    if len(text) <= limit:
        return text, False
    return f"[first {len(text) - limit} characters omitted]\n" + text[-limit:], True


def _scrub(text: str) -> str:
    from log_sanitizer import sanitize

    return sanitize(text) or ""


class RunStore:
    """sqlite mirror of run records. Best effort: a database that cannot be opened never fails a run."""

    def __init__(self, path):
        self._path = Path(path)
        self._lock = threading.Lock()
        self._ready = False

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self._path, timeout=5)
        if not self._ready:
            self._path.parent.mkdir(parents=True, exist_ok=True)
            conn.execute(
                "CREATE TABLE IF NOT EXISTS runs (id TEXT PRIMARY KEY, context_id TEXT NOT NULL, state TEXT NOT NULL, "
                "created_at REAL NOT NULL, finished_at REAL NOT NULL, rev INTEGER NOT NULL, data TEXT NOT NULL)")
            conn.execute("CREATE INDEX IF NOT EXISTS runs_context ON runs (context_id, created_at)")
            self._ready = True
        return conn

    def _run(self, work, default=None):
        with self._lock:
            try:
                self._path.parent.mkdir(parents=True, exist_ok=True)
                conn = self._connect()
                try:
                    with conn:
                        return work(conn)
                finally:
                    conn.close()
            except (sqlite3.Error, OSError) as exc:
                _log.warning("run store unavailable (%s)", type(exc).__name__)
                return default

    def upsert(self, record: dict) -> None:
        data = dict(record)
        data["output_tail"] = _scrub(str(data.get("output_tail") or ""))[-OUTPUT_TAIL_CHARS - 80:]
        data["error"] = _scrub(str(data.get("error") or ""))[:500]
        self._run(lambda conn: conn.execute(
            "INSERT INTO runs (id, context_id, state, created_at, finished_at, rev, data) VALUES (?,?,?,?,?,?,?) "
            "ON CONFLICT(id) DO UPDATE SET state=excluded.state, finished_at=excluded.finished_at, "
            "rev=excluded.rev, data=excluded.data WHERE excluded.rev >= runs.rev",
            (data["id"], data["context_id"], data["state"], data.get("created_at", 0.0),
             data.get("finished_at", 0.0), data.get("rev", 0), json.dumps(data))))

    def get(self, run_id: str) -> dict | None:
        row = self._run(lambda conn: conn.execute("SELECT data FROM runs WHERE id=?", (run_id,)).fetchone())
        return json.loads(row[0]) if row else None

    def list(self, context_id: str, limit: int = 50) -> list[dict]:
        rows = self._run(lambda conn: conn.execute(
            "SELECT data FROM runs WHERE context_id=? ORDER BY created_at DESC LIMIT ?", (context_id, limit)).fetchall(), [])
        return [json.loads(r[0]) for r in rows]

    def interrupt_active(self, now: float) -> list[dict]:
        """Startup: records that were still active when the backend stopped become interrupted."""
        marks = ",".join("?" * len(ACTIVE_STATES))

        def work(conn):
            rows = conn.execute(f"SELECT data FROM runs WHERE state IN ({marks})", tuple(ACTIVE_STATES)).fetchall()
            changed = []
            for (raw,) in rows:
                data = json.loads(raw)
                data.update(state="interrupted", finished_at=now, rev=int(data.get("rev", 0)) + 1)
                conn.execute("UPDATE runs SET state=?, finished_at=?, rev=?, data=? WHERE id=?",
                             ("interrupted", now, data["rev"], json.dumps(data), data["id"]))
                changed.append(data)
            return changed

        return self._run(work, [])

    def purge(self, older_than: float) -> None:
        marks = ",".join("?" * len(ACTIVE_STATES))
        self._run(lambda conn: conn.execute(
            f"DELETE FROM runs WHERE state NOT IN ({marks}) AND MAX(finished_at, created_at) < ?",
            (*ACTIVE_STATES, older_than)))
