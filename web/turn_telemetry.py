"""Structured turn-event logging for triage.

Every LLM turn — start and end — is logged to the turn_log SQLite table with
enough context to reconstruct the full conversation lifecycle and triage
stuck/stalled/errored turns.

Design constraints (matching perf.py's philosophy):
  - SQLite-persisted (survives restart, unlike perf.py's in-memory buffers).
  - Records ONLY metadata: turn IDs, outcome, token counts, error messages
    (truncated), tool names. NEVER message content, tool inputs, or tool
    outputs — those live in conversation_store.
  - Async via aiosqlite (non-blocking on the event loop).
  - All logging calls are best-effort: a telemetry failure must never break
    a chat turn. Every public function wraps its DB write in try/except and
    logs a warning on failure.
"""
from __future__ import annotations

import json
import logging
import time
import uuid
from datetime import datetime, timezone

import aiosqlite

from config import TASKS_DB as DB_PATH

_log = logging.getLogger(__name__)

_MAX_ERROR_LEN = 500

# In-memory map: context_id -> (last_turn_id, last_turn_end_ts).
# Used by link_next_turn to fill next_turn_id / next_turn_delay_s on the
# previous turn's row when a new turn starts in the same context. Cleared on
# restart (acceptable — only links turns within a single process lifetime).
_last_turn_by_context: dict[str, tuple[str, float]] = {}


async def init_table() -> None:
    """Create the turn_log table if it doesn't exist. Called from
    task_queue.init_db() alongside the existing usage_log table creation."""
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("""
            CREATE TABLE IF NOT EXISTS turn_log (
                id              INTEGER PRIMARY KEY AUTOINCREMENT,
                turn_id         TEXT NOT NULL,
                context_id      TEXT NOT NULL,
                task_id         TEXT NOT NULL,
                turn_index      INTEGER NOT NULL,
                agent           TEXT NOT NULL,
                model           TEXT NOT NULL,
                provider        TEXT NOT NULL,
                outcome         TEXT NOT NULL,
                stop_reason     TEXT,
                tool_calls      TEXT NOT NULL DEFAULT '[]',
                tool_error      TEXT,
                llm_error       TEXT,
                input_tokens    INTEGER NOT NULL DEFAULT 0,
                output_tokens   INTEGER NOT NULL DEFAULT 0,
                overflow_prunes INTEGER NOT NULL DEFAULT 0,
                retry_count     INTEGER NOT NULL DEFAULT 0,
                failover_used   INTEGER NOT NULL DEFAULT 0,
                bad_tool_streak INTEGER NOT NULL DEFAULT 0,
                duration_ms     INTEGER NOT NULL DEFAULT 0,
                history_turns   INTEGER NOT NULL DEFAULT 0,
                active_skills   TEXT NOT NULL DEFAULT '[]',
                next_turn_id    TEXT,
                next_turn_delay_s REAL,
                created_at      TEXT NOT NULL
            )
        """)
        await db.execute("CREATE INDEX IF NOT EXISTS idx_turn_log_context ON turn_log(context_id, created_at)")
        await db.execute("CREATE INDEX IF NOT EXISTS idx_turn_log_task ON turn_log(task_id)")
        await db.execute("CREATE INDEX IF NOT EXISTS idx_turn_log_outcome ON turn_log(outcome)")
        await db.commit()


def _truncate(s: str | None) -> str | None:
    if s is None:
        return None
    if len(s) > _MAX_ERROR_LEN:
        return s[:_MAX_ERROR_LEN] + "…"
    return s


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


async def log_turn_start(
    turn_id: str,
    context_id: str,
    task_id: str,
    turn_index: int,
    agent: str,
    model: str,
    provider: str,
    history_turns: int,
    active_skills: list[str],
) -> None:
    """Record the start of a turn. Best-effort; never raises.

    Note: next-turn linking is done in log_turn_end (which links the NEW turn
    to the PREVIOUS one's row by updating it). This function is a no-op stub
    kept for API symmetry — the start-time data (model, provider, history_turns,
    active_skills) is passed through to log_turn_end instead, so no row is
    written here."""
    pass


async def log_turn_end(
    turn_id: str,
    context_id: str,
    task_id: str,
    turn_index: int,
    agent: str,
    model: str,
    provider: str,
    outcome: str,
    stop_reason: str | None,
    tool_calls: list[dict],
    tool_error: str | None,
    llm_error: str | None,
    input_tokens: int,
    output_tokens: int,
    overflow_prunes: int,
    retry_count: int,
    failover_used: bool,
    bad_tool_streak: int,
    duration_ms: int,
    history_turns: int = 0,
    active_skills: list[str] | None = None,
) -> None:
    """Record the end of a turn. Called at EVERY exit path in the agent loop."""
    try:
        async with aiosqlite.connect(DB_PATH) as db:
            # Link to previous turn in this context: update the previous row's
            # next_turn_id + next_turn_delay_s so you can see if the user
            # continued or gave up after an error.
            prev = _last_turn_by_context.get(context_id)
            if prev is not None:
                prev_turn_id, prev_end_ts = prev
                delay = round(time.time() - prev_end_ts, 2)
                try:
                    await db.execute(
                        "UPDATE turn_log SET next_turn_id = ?, next_turn_delay_s = ? WHERE turn_id = ?",
                        (turn_id, delay, prev_turn_id),
                    )
                except Exception as exc:
                    _log.warning("[turn_telemetry] failed to link turns: %s", exc)

            await db.execute(
                """INSERT INTO turn_log (
                    turn_id, context_id, task_id, turn_index, agent, model, provider,
                    outcome, stop_reason, tool_calls, tool_error, llm_error,
                    input_tokens, output_tokens, overflow_prunes, retry_count,
                    failover_used, bad_tool_streak, duration_ms,
                    history_turns, active_skills, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    turn_id, context_id, task_id, turn_index, agent, model, provider,
                    outcome, stop_reason,
                    json.dumps(tool_calls),
                    _truncate(tool_error),
                    _truncate(llm_error),
                    input_tokens, output_tokens, overflow_prunes, retry_count,
                    1 if failover_used else 0, bad_tool_streak, duration_ms,
                    history_turns,
                    json.dumps(active_skills or []),
                    _now_iso(),
                ),
            )
            await db.commit()
        # Track this as the latest turn for this context (for next-turn linking)
        _last_turn_by_context[context_id] = (turn_id, time.time())
    except Exception as exc:
        _log.warning("[turn_telemetry] failed to log turn end: %s", exc)


def new_turn_id() -> str:
    """Generate a fresh turn_id."""
    return str(uuid.uuid4())


async def get_conversation_timeline(context_id: str, limit: int = 100) -> list[dict]:
    """Return all turns for a conversation, ordered by time. The primary triage
    query. Each row includes next_turn_id / next_turn_delay_s so you can see if
    the user continued or gave up."""
    try:
        async with aiosqlite.connect(DB_PATH) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute(
                """SELECT * FROM turn_log WHERE context_id = ?
                   ORDER BY created_at ASC LIMIT ?""",
                (context_id, limit),
            ) as cur:
                rows = await cur.fetchall()
                return [_row_to_dict(r) for r in rows]
    except Exception as exc:
        _log.warning("[turn_telemetry] failed to get timeline: %s", exc)
        return []


async def get_turns_by_outcome(outcome: str, limit: int = 50) -> list[dict]:
    """Find all turns with a given outcome (e.g. all 'stalled' turns)."""
    try:
        async with aiosqlite.connect(DB_PATH) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute(
                """SELECT * FROM turn_log WHERE outcome = ?
                   ORDER BY created_at DESC LIMIT ?""",
                (outcome, limit),
            ) as cur:
                rows = await cur.fetchall()
                return [_row_to_dict(r) for r in rows]
    except Exception as exc:
        _log.warning("[turn_telemetry] failed to get turns by outcome: %s", exc)
        return []


async def get_stuck_conversations() -> list[dict]:
    """Find conversations where the last turn was 'stalled' or 'llm_error' AND
    no follow-up turn was logged (next_turn_id IS NULL) — i.e. the user likely
    gave up. Returns the stuck turn rows, most recent first."""
    try:
        async with aiosqlite.connect(DB_PATH) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute(
                """SELECT * FROM turn_log
                   WHERE outcome IN ('stalled', 'llm_error', 'circuit_breaker', 'max_iterations')
                     AND next_turn_id IS NULL
                   ORDER BY created_at DESC LIMIT 100""",
            ) as cur:
                rows = await cur.fetchall()
                return [_row_to_dict(r) for r in rows]
    except Exception as exc:
        _log.warning("[turn_telemetry] failed to get stuck conversations: %s", exc)
        return []


def _row_to_dict(row: aiosqlite.Row) -> dict:
    d = dict(row)
    # Parse JSON columns back to lists
    for col in ("tool_calls", "active_skills"):
        raw = d.get(col)
        if isinstance(raw, str):
            try:
                d[col] = json.loads(raw)
            except (json.JSONDecodeError, TypeError):
                d[col] = []
    return d
