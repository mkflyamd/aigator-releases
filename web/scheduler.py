"""Scheduled-job engine — APScheduler 3.x with SQLite persistence.

APScheduler manages its own ``apscheduler_jobs`` table via SQLAlchemy.
We maintain two *additional* tables (``job_meta`` and ``job_history``)
using the same aiosqlite pattern as task_queue.py.

When a trigger fires, ``_execute_job`` enqueues the prompt into the
existing task-queue worker so it flows through the normal three-agent
loop.
"""

import json
import logging
import uuid
from datetime import datetime, timezone
from pathlib import Path

import aiosqlite
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.jobstores.sqlalchemy import SQLAlchemyJobStore
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.date import DateTrigger
from apscheduler.triggers.interval import IntervalTrigger

import task_queue

_log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Database path (shared directory with tasks.db)
# ---------------------------------------------------------------------------
DB_PATH = Path.home() / "AppData" / "Roaming" / "AIGator" / "scheduler.db"

# ---------------------------------------------------------------------------
# APScheduler instance (module-level singleton)
# ---------------------------------------------------------------------------
_scheduler = AsyncIOScheduler(
    jobstores={"default": SQLAlchemyJobStore(url=f"sqlite:///{DB_PATH}")},
    timezone=None,  # None → uses system local timezone via tzlocal
    job_defaults={"misfire_grace_time": 3600},
)

# ---------------------------------------------------------------------------
# Custom-table DDL
# ---------------------------------------------------------------------------
_DDL_JOB_META = """
CREATE TABLE IF NOT EXISTS job_meta (
    job_id          TEXT PRIMARY KEY,
    name            TEXT NOT NULL,
    prompt          TEXT NOT NULL,
    trigger_type    TEXT NOT NULL,
    trigger_args    TEXT NOT NULL,
    token_budget    INTEGER DEFAULT 0,
    skills          TEXT DEFAULT '[]',
    tab_context_id  TEXT,
    created_at      TEXT NOT NULL
);
"""

_DDL_ADD_SKILLS_COL = "ALTER TABLE job_meta ADD COLUMN skills TEXT DEFAULT '[]'"
_DDL_ADD_TAB_COL = "ALTER TABLE job_meta ADD COLUMN tab_context_id TEXT"

_DDL_JOB_HISTORY = """
CREATE TABLE IF NOT EXISTS job_history (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    job_id        TEXT NOT NULL,
    task_id       TEXT NOT NULL,
    started_at    TEXT NOT NULL,
    completed_at  TEXT,
    status        TEXT,
    input_tokens  INTEGER DEFAULT 0,
    output_tokens INTEGER DEFAULT 0
);
"""


# ── Pin injection helper ───────────────────────────────────────────────────

def _render_pins_block(tab_context_id: str) -> tuple[str, list[str]]:
    """Return (prompt_prefix, pin_source_skills) for a tab's pinned items.

    Brief by design — scheduled runs don't carry conversational context, so we
    just enumerate what's pinned and let the LLM call the right read tools.
    """
    from skills.context.state import get_pins
    from skills.context import tabs as _tabs_registry

    pins = get_pins(tab_context_id)
    if not pins:
        return "", []

    tab_name = _tabs_registry.get_name(tab_context_id) or tab_context_id
    lines = []
    skills_seen: set[str] = set()
    _source_skill_map = {"word": "docx", "excel": "excel", "ppt": "ppt"}
    for p in pins:
        s, pid, lbl = p.get("source"), p.get("id"), p.get("label")
        lines.append(f"- {s}: \"{lbl}\" (id: {pid})")
        if s in _source_skill_map:
            skills_seen.add(_source_skill_map[s])
        elif s:
            skills_seen.add(s)

    prefix = (
        f"\U0001f4cc PINNED CONTEXT for tab \"{tab_name}\" "
        f"({len(lines)} item{'s' if len(lines) != 1 else ''}):\n"
        + "\n".join(lines)
        + "\n\nUse get_tab_pins for details, or the appropriate read tool "
        "(read_email, get_confluence_page, read_teams_chats, etc.) to fetch "
        "content for any pinned item.\n\n---\n\n"
    )
    return prefix, sorted(skills_seen)


# ── Internal execution function ────────────────────────────────────────────

async def _execute_job(job_id: str) -> None:
    """Called by APScheduler when a trigger fires."""
    # 1. Read prompt + skills from job_meta
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            "SELECT prompt, skills, tab_context_id FROM job_meta WHERE job_id = ?",
            (job_id,),
        ) as cur:
            row = await cur.fetchone()
    if row is None:
        return  # metadata missing — nothing we can do

    prompt: str = row["prompt"]
    skills: list[str] = json.loads(row["skills"] or "[]")
    tab_context_id: str | None = row["tab_context_id"]

    # Inject pinned-context prefix if this job is bound to a tab
    if tab_context_id:
        prefix, pin_skills = _render_pins_block(tab_context_id)
        if prefix:
            prompt = prefix + prompt
        for sid in pin_skills:
            if sid not in skills:
                skills.append(sid)

    # Auto-detect browser skill if prompt mentions URLs or browser-intent keywords
    if "browser" not in skills:
        _prompt_lower = prompt.lower()
        _BROWSER_SIGNALS = [
            "http://", "https://", "www.",
            ".com/", ".org/", ".net/", ".io/",
            "go to", "visit", "check site", "check the site",
            "search for", "browse", "look up online",
            "open the page", "open the site", "pricing page",
        ]
        if any(signal in _prompt_lower for signal in _BROWSER_SIGNALS):
            skills = skills + ["browser"]
            _log.info("[scheduler] Auto-detected browser intent in job %s prompt", job_id)

    # 2. Enqueue into the task queue (reuses the three-agent loop).
    # context_id stays as job_id (its own space) — never the bound tab's id,
    # because the "View in this chat" button in agents-pane.js routes results
    # by matching context_id against open tabs. If we used the tab's id here,
    # viewing a scheduled result would hijack the user's tab view.
    task_id = await task_queue.enqueue(prompt, skills=skills, context_id=job_id)

    # 3. Record in job_history
    now = datetime.now(timezone.utc).isoformat()
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "INSERT INTO job_history (job_id, task_id, started_at, status) VALUES (?, ?, ?, 'pending')",
            (job_id, task_id, now),
        )
        await db.commit()


# ── Trigger factory ─────────────────────────────────────────────────────────

_TRIGGER_MAP = {
    "cron": CronTrigger,
    "interval": IntervalTrigger,
    "date": DateTrigger,
}


def _make_trigger(trigger_type: str, trigger_args: dict):
    cls = _TRIGGER_MAP.get(trigger_type)
    if cls is None:
        raise ValueError(f"Unknown trigger_type: {trigger_type!r}. Must be one of {list(_TRIGGER_MAP)}")
    return cls(**trigger_args)


# ── Public API ──────────────────────────────────────────────────────────────

async def init_scheduler() -> None:
    """Create custom tables, start APScheduler, re-register callables."""
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)

    # Create our custom tables
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(_DDL_JOB_META)
        await db.execute(_DDL_JOB_HISTORY)
        # Migrations: add new columns if missing (existing DBs)
        for _ddl in (_DDL_ADD_SKILLS_COL, _DDL_ADD_TAB_COL):
            try:
                await db.execute(_ddl)
            except Exception:
                pass  # column already exists
        await db.commit()

    # Start the scheduler (also opens/creates the apscheduler_jobs table)
    _scheduler.start()

    # Re-register the callable for every persisted job.
    # APScheduler persists trigger state but NOT the Python callable reference.
    for job in _scheduler.get_jobs():
        job.modify(func=_execute_job)


async def shutdown_scheduler() -> None:
    """Graceful shutdown."""
    _scheduler.shutdown(wait=False)


async def add_job(
    name: str,
    prompt: str,
    trigger_type: str,
    trigger_args: dict,
    token_budget: int = 0,
    end_date: str | None = None,
    skills: list[str] | None = None,
    tab_context_id: str | None = None,
) -> dict:
    """Add a scheduled job. Returns metadata dict with job_id and next_run_time."""
    job_id = str(uuid.uuid4())

    # Inject end_date into trigger_args for APScheduler (interval and cron support it natively)
    if end_date and trigger_type in ("interval", "cron"):
        trigger_args = {**trigger_args, "end_date": end_date}

    trigger = _make_trigger(trigger_type, trigger_args)

    # Register with APScheduler
    ap_job = _scheduler.add_job(
        _execute_job,
        trigger=trigger,
        args=[job_id],
        id=job_id,
    )

    # Persist our metadata
    now = datetime.now(timezone.utc).isoformat()
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "INSERT INTO job_meta (job_id, name, prompt, trigger_type, trigger_args, token_budget, skills, tab_context_id, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (job_id, name, prompt, trigger_type, json.dumps(trigger_args), token_budget, json.dumps(skills or []), tab_context_id, now),
        )
        await db.commit()

    next_run = ap_job.next_run_time.isoformat() if ap_job.next_run_time else None

    # Notify frontend so agents pane updates immediately (no polling needed)
    try:
        import shared
        shared.notify_all({"type": "job_created", "job_id": job_id, "name": name})
    except Exception:
        pass

    return {"job_id": job_id, "name": name, "next_run_time": next_run}


async def remove_job(job_id: str) -> bool:
    """Remove job from APScheduler and delete from job_meta."""
    try:
        _scheduler.remove_job(job_id)
    except Exception:
        pass  # already gone from APScheduler

    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute("DELETE FROM job_meta WHERE job_id = ?", (job_id,))
        await db.commit()
        return cur.rowcount > 0


async def pause_job(job_id: str) -> bool:
    """Pause a job."""
    try:
        _scheduler.pause_job(job_id)
        return True
    except Exception:
        return False


async def resume_job(job_id: str) -> bool:
    """Resume a paused job."""
    try:
        _scheduler.resume_job(job_id)
        return True
    except Exception:
        return False


async def run_job_now(job_id: str) -> str:
    """Trigger immediate execution. Returns task_id from enqueue."""
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            "SELECT prompt, skills, tab_context_id FROM job_meta WHERE job_id = ?",
            (job_id,),
        ) as cur:
            row = await cur.fetchone()
    if row is None:
        raise ValueError(f"No job with id {job_id}")

    skills = json.loads(row["skills"] or "[]")
    prompt = row["prompt"]
    tab_context_id = row["tab_context_id"]
    if tab_context_id:
        prefix, pin_skills = _render_pins_block(tab_context_id)
        if prefix:
            prompt = prefix + prompt
        for sid in pin_skills:
            if sid not in skills:
                skills.append(sid)
    task_id = await task_queue.enqueue(prompt, skills=skills, context_id=job_id)

    now = datetime.now(timezone.utc).isoformat()
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "INSERT INTO job_history (job_id, task_id, started_at, status) VALUES (?, ?, ?, 'pending')",
            (job_id, task_id, now),
        )
        await db.commit()

    return task_id


async def list_jobs() -> list[dict]:
    """List all jobs with next_run_time and last run info from job_history."""
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute("SELECT * FROM job_meta ORDER BY created_at DESC") as cur:
            rows = [dict(r) for r in await cur.fetchall()]

    # Enrich with APScheduler state and latest history row
    for row in rows:
        row["trigger_args"] = json.loads(row["trigger_args"])
        jid = row["job_id"]

        # APScheduler state
        ap_job = _scheduler.get_job(jid)
        if ap_job is not None:
            row["next_run_time"] = ap_job.next_run_time.isoformat() if ap_job.next_run_time else None
            row["paused"] = ap_job.next_run_time is None
        else:
            row["next_run_time"] = None
            row["paused"] = False

        # Last run from history
        async with aiosqlite.connect(DB_PATH) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute(
                "SELECT * FROM job_history WHERE job_id = ? ORDER BY started_at DESC LIMIT 1",
                (jid,),
            ) as cur:
                last = await cur.fetchone()
        row["last_run"] = dict(last) if last else None

    return rows


_TAB_SENTINEL = object()  # distinguish "not provided" from explicit None (clear binding)


async def update_job(
    job_id: str,
    name: str | None = None,
    prompt: str | None = None,
    trigger_type: str | None = None,
    trigger_args: dict | None = None,
    end_date: str | None = None,
    tab_context_id=_TAB_SENTINEL,
) -> dict | None:
    """Update name, prompt, and/or schedule of an existing job."""
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute("SELECT * FROM job_meta WHERE job_id = ?", (job_id,)) as cur:
            row = await cur.fetchone()
        if row is None:
            return None
        new_name = name if name is not None else row["name"]
        new_prompt = prompt if prompt is not None else row["prompt"]
        new_trigger_type = trigger_type if trigger_type is not None else row["trigger_type"]
        new_trigger_args = trigger_args if trigger_args is not None else json.loads(row["trigger_args"])
        new_tab_context_id = (
            row["tab_context_id"] if tab_context_id is _TAB_SENTINEL else tab_context_id
        )

        # Inject end_date into trigger_args for APScheduler
        if end_date and new_trigger_type in ("interval", "cron"):
            new_trigger_args = {**new_trigger_args, "end_date": end_date}
        elif end_date is None and trigger_args is not None:
            # Caller explicitly sent new trigger_args without end_date — strip it
            new_trigger_args.pop("end_date", None)

        await db.execute(
            "UPDATE job_meta SET name = ?, prompt = ?, trigger_type = ?, trigger_args = ?, tab_context_id = ? WHERE job_id = ?",
            (new_name, new_prompt, new_trigger_type, json.dumps(new_trigger_args), new_tab_context_id, job_id),
        )
        await db.commit()

    # Re-register with APScheduler if trigger changed
    if trigger_type is not None or trigger_args is not None or end_date is not None:
        try:
            _scheduler.remove_job(job_id)
        except Exception:
            pass
        trigger = _make_trigger(new_trigger_type, new_trigger_args)
        _scheduler.add_job(_execute_job, trigger=trigger, args=[job_id], id=job_id)

    next_run = None
    ap_job = _scheduler.get_job(job_id)
    if ap_job and ap_job.next_run_time:
        next_run = ap_job.next_run_time.isoformat()

    return {"job_id": job_id, "name": new_name, "prompt": new_prompt,
            "trigger_type": new_trigger_type, "trigger_args": new_trigger_args,
            "tab_context_id": new_tab_context_id, "next_run_time": next_run}


async def get_job(job_id: str) -> dict | None:
    """Get single job with full history."""
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute("SELECT * FROM job_meta WHERE job_id = ?", (job_id,)) as cur:
            row = await cur.fetchone()
    if row is None:
        return None

    result = dict(row)
    result["trigger_args"] = json.loads(result["trigger_args"])

    ap_job = _scheduler.get_job(job_id)
    if ap_job is not None:
        result["next_run_time"] = ap_job.next_run_time.isoformat() if ap_job.next_run_time else None
        result["paused"] = ap_job.next_run_time is None
    else:
        result["next_run_time"] = None
        result["paused"] = False

    import task_queue as _tq
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            "SELECT * FROM job_history WHERE job_id = ? ORDER BY started_at DESC", (job_id,)
        ) as cur:
            history_rows = [dict(r) for r in await cur.fetchall()]

    # Attach context_id from the tasks DB so the frontend can route "view this chat"
    for row in history_rows:
        task = await _tq.get_task(row["task_id"])
        row["context_id"] = task["context_id"] if task else None

    result["history"] = history_rows
    return result


async def get_job_history(job_id: str = None, limit: int = 20) -> list[dict]:
    """Execution history, optionally filtered by job_id."""
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        if job_id:
            async with db.execute(
                "SELECT * FROM job_history WHERE job_id = ? ORDER BY started_at DESC LIMIT ?",
                (job_id, limit),
            ) as cur:
                return [dict(r) for r in await cur.fetchall()]
        else:
            async with db.execute(
                "SELECT * FROM job_history ORDER BY started_at DESC LIMIT ?",
                (limit,),
            ) as cur:
                return [dict(r) for r in await cur.fetchall()]


async def get_job_for_task(task_id: str) -> dict | None:
    """Look up the job that spawned this task_id, if any."""
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            "SELECT jm.* FROM job_meta jm JOIN job_history jh ON jm.job_id = jh.job_id WHERE jh.task_id = ?",
            (task_id,),
        ) as cur:
            row = await cur.fetchone()
            return dict(row) if row else None


async def update_history_for_task(
    task_id: str, status: str, input_tokens: int, output_tokens: int
) -> None:
    """Called by lifespan callback when a task completes.

    Updates the most recent job_history row matching *task_id* (if any).
    Tasks not originating from the scheduler will simply have no matching
    row, so this is a safe no-op.
    """
    now = datetime.now(timezone.utc).isoformat()
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "UPDATE job_history SET completed_at = ?, status = ?, input_tokens = ?, output_tokens = ? "
            "WHERE task_id = ?",
            (now, status, input_tokens, output_tokens, task_id),
        )
        await db.commit()
