"""Durable, task-bound mirror of HITL drafts — GitHub issue #54.

skills/_drafts.py's _pending_drafts is in-memory, per-process, with a 30
minute TTL tuned for an interactive chat session where the user is at the
keyboard. A scheduled job's draft has no such guarantee: the user may open
the completed task hours (realistically: the next morning) later, and the
backend may have restarted in between. This module persists a durable copy
of every draft created during a scheduled/background task's execution
(keyed by task_id) so:

  - GET /api/tasks/{task_id} can return enough data to re-render the exact
    HITL approval card, without touching the live in-memory store at all.
  - If the live in-memory draft is gone (server restart, or its own 30-min
    TTL lapsed) but this durable row is still "pending" and not itself
    past TASK_DRAFT_TTL_SECONDS, routes/drafts.py can rehydrate it back
    into _pending_drafts on demand so Approve still works.

This module has zero knowledge of draft *semantics* (email vs Slack vs
Jira, etc.) — it only stores/retrieves opaque JSON blobs keyed by
draft_id/task_id and mirrors the same status strings skills/_drafts.py
already uses ("pending", "sending", "handing_off", "handed_off"), plus one
additional terminal value this module writes itself: "sent" (written once,
right after a live approve's pop_draft() succeeds — pop_draft() deletes
the in-memory record entirely, so this durable row becomes the only
remaining evidence of what happened for a task opened again later).

Schema lives in TASKS_DB (config.TASKS_DB) since it's keyed by task_id and
read by the same GET /api/tasks/{task_id} route that already returns the
task row — not scheduler.db, which is keyed by job_id and knows nothing
about individual tool calls a job's prompt happened to trigger.
"""

import json
from datetime import datetime, timezone

import aiosqlite

from config import TASKS_DB as DB_PATH

# A scheduled job's draft must survive the user coming back hours later —
# realistically, overnight — unlike skills/_drafts.py's 30-minute TTL, which
# assumes an interactive session where the user is still at the keyboard.
TASK_DRAFT_TTL_SECONDS = 7 * 24 * 3600  # 7 days

_DDL_TASK_DRAFTS = """
CREATE TABLE IF NOT EXISTS task_drafts (
    draft_id    TEXT PRIMARY KEY,
    task_id     TEXT NOT NULL,
    draft_type  TEXT NOT NULL,
    draft_data  TEXT NOT NULL,
    params      TEXT NOT NULL,
    status      TEXT NOT NULL DEFAULT 'pending',
    created_at  TEXT NOT NULL,
    updated_at  TEXT NOT NULL
)
"""


async def init_table() -> None:
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(_DDL_TASK_DRAFTS)
        await db.execute(
            "CREATE INDEX IF NOT EXISTS idx_task_drafts_task_id ON task_drafts(task_id)"
        )
        await db.commit()


async def record_draft(
    task_id: str, draft_id: str, draft_type: str, draft_data: dict, params: dict
) -> None:
    """Durably record a draft created during a task's execution.

    Called once, right after the tool call that created it returns (see
    task_queue._run_task's "draft" SSE-chunk handling) — draft_data is the
    exact display payload the interactive-chat frontend already knows how
    to render (_injectDraftApprovalCard); params is the live in-memory
    _pending_drafts[draft_id]["params"] at that moment, kept durably so a
    restart-recovery rehydrate has the mutation payload approve_draft
    actually needs, not just display fields.
    """
    now = datetime.now(timezone.utc).isoformat()
    async with aiosqlite.connect(DB_PATH) as db:
        # INSERT OR IGNORE, not OR REPLACE: draft_id is a fresh uuid4 per
        # create_draft() call today, so a genuine duplicate call for the
        # same draft_id should never happen — but if it ever did (a future
        # SSE-reconnect replay, a retried chunk, etc.), REPLACE would
        # silently reset an already-"sent"/"sending" row's status and
        # created_at back to a fresh "pending", making an already-delivered
        # draft look re-approvable. IGNORE makes a duplicate call a no-op.
        await db.execute(
            "INSERT OR IGNORE INTO task_drafts "
            "(draft_id, task_id, draft_type, draft_data, params, status, created_at, updated_at) "
            "VALUES (?, ?, ?, ?, ?, 'pending', ?, ?)",
            (draft_id, task_id, draft_type, json.dumps(draft_data), json.dumps(params), now, now),
        )
        await db.commit()


async def sync_status(draft_id: str, status: str) -> None:
    """Mirror a live _pending_drafts status transition into the durable
    row, if one exists for this draft_id (a plain interactive-chat draft
    has no row here at all — this UPDATE simply matches zero rows, which
    is fine; callers don't need to know in advance whether a draft is
    task-bound)."""
    now = datetime.now(timezone.utc).isoformat()
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "UPDATE task_drafts SET status=?, updated_at=? WHERE draft_id=?",
            (status, now, draft_id),
        )
        await db.commit()


def _is_expired(created_at_iso: str) -> bool:
    created = datetime.fromisoformat(created_at_iso)
    if created.tzinfo is None:
        created = created.replace(tzinfo=timezone.utc)
    return (datetime.now(timezone.utc) - created).total_seconds() > TASK_DRAFT_TTL_SECONDS


async def list_for_task(task_id: str) -> list[dict]:
    """Return every durable draft for a task, for GET /api/tasks/{task_id}
    to attach as t["drafts"]. Never includes params (the mutation
    payload) — that's an internal, approve-time-only concern, not
    something the frontend needs to render a card."""
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            "SELECT draft_id, task_id, draft_type, draft_data, status, created_at, updated_at "
            "FROM task_drafts WHERE task_id=? ORDER BY created_at",
            (task_id,),
        ) as cur:
            rows = [dict(r) for r in await cur.fetchall()]
    out = []
    for r in rows:
        r["draft_data"] = json.loads(r["draft_data"])
        # Computed regardless of status (not just "pending"): a "sending"/
        # "handing_off" row is also age-bounded for rehydration purposes
        # (see routes/drafts.py._ensure_draft_loaded), and a "sent" row's
        # expired flag being (harmlessly) true past the TTL never matters
        # to the frontend — its status-keyed label branch is checked first.
        r["expired"] = _is_expired(r["created_at"])
        out.append(r)
    return out


async def get_for_rehydrate(draft_id: str) -> dict | None:
    """Return the full durable row (including params) needed to rehydrate
    _pending_drafts after a restart, or None if unknown. Only useful to the
    caller when status == "pending" and not expired — callers must check
    both themselves (this function does no filtering, so tests/diagnostics
    can also inspect a non-pending row)."""
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            "SELECT * FROM task_drafts WHERE draft_id=?", (draft_id,)
        ) as cur:
            row = await cur.fetchone()
    if not row:
        return None
    r = dict(row)
    r["draft_data"] = json.loads(r["draft_data"])
    r["params"] = json.loads(r["params"])
    r["expired"] = _is_expired(r["created_at"])
    return r
