"""Background task queue — SQLite-backed, asyncio worker.

Schema (tasks.db):
  task_id       TEXT PRIMARY KEY
  prompt        TEXT NOT NULL
  status        TEXT NOT NULL  -- pending | running | done | failed | cancelled
  created_at    TEXT NOT NULL  -- ISO8601
  completed_at  TEXT
  result        TEXT
  input_tokens  INTEGER DEFAULT 0
  output_tokens INTEGER DEFAULT 0
"""
import asyncio, json, uuid
from datetime import datetime, timedelta, timezone
import aiosqlite

from config import TASKS_DB as DB_PATH
_worker_task = None
_notify_callback = None


def set_notify_callback(cb):
    global _notify_callback
    _notify_callback = cb


async def init_db():
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("""
            CREATE TABLE IF NOT EXISTS tasks (
                task_id       TEXT PRIMARY KEY,
                prompt        TEXT NOT NULL,
                status        TEXT NOT NULL DEFAULT 'pending',
                created_at    TEXT NOT NULL,
                completed_at  TEXT,
                result        TEXT,
                input_tokens  INTEGER DEFAULT 0,
                output_tokens INTEGER DEFAULT 0
            )
        """)
        # Usage log — tracks ALL token usage (interactive chat + background tasks)
        await db.execute("""
            CREATE TABLE IF NOT EXISTS usage_log (
                id            INTEGER PRIMARY KEY AUTOINCREMENT,
                source        TEXT NOT NULL DEFAULT 'chat',
                prompt_preview TEXT,
                input_tokens  INTEGER DEFAULT 0,
                output_tokens INTEGER DEFAULT 0,
                created_at    TEXT NOT NULL
            )
        """)
        # Migration: add columns if missing (existing DBs)
        for col_sql in [
            "ALTER TABLE tasks ADD COLUMN skills TEXT DEFAULT '[]'",
            "ALTER TABLE tasks ADD COLUMN pane_data TEXT",
            "ALTER TABLE tasks ADD COLUMN context_id TEXT",
        ]:
            try:
                await db.execute(col_sql)
            except Exception:
                pass
        # Recover tasks that were running when the process was killed
        await db.execute("UPDATE tasks SET status='pending' WHERE status='running'")
        await db.commit()


async def enqueue(prompt: str, skills: list[str] | None = None, context_id: str | None = None) -> str:
    task_id = str(uuid.uuid4())
    now = datetime.now(timezone.utc).isoformat()
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "INSERT INTO tasks (task_id, prompt, status, created_at, skills, context_id) VALUES (?, ?, 'pending', ?, ?, ?)",
            (task_id, prompt, now, json.dumps(skills or []), context_id),
        )
        await db.commit()
    return task_id


async def get_task(task_id: str):
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute("SELECT * FROM tasks WHERE task_id = ?", (task_id,)) as cur:
            row = await cur.fetchone()
            return dict(row) if row else None


async def log_usage(source: str, prompt_preview: str, input_tokens: int, output_tokens: int):
    """Log token usage for any response (chat or background)."""
    now = datetime.now(timezone.utc).isoformat()
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "INSERT INTO usage_log (source, prompt_preview, input_tokens, output_tokens, created_at) VALUES (?, ?, ?, ?, ?)",
            (source, (prompt_preview or "")[:100], input_tokens, output_tokens, now),
        )
        await db.commit()


async def get_usage_summary() -> dict:
    """Return token usage summary: today, this week, all time."""
    async with aiosqlite.connect(DB_PATH) as db:
        now = datetime.now(timezone.utc)
        today = now.strftime("%Y-%m-%d")
        week_ago = (now - timedelta(days=7)).strftime("%Y-%m-%d")
        # Today
        async with db.execute(
            "SELECT COALESCE(SUM(input_tokens),0), COALESCE(SUM(output_tokens),0), COUNT(*) FROM usage_log WHERE created_at >= ?",
            (today,)
        ) as cur:
            row = await cur.fetchone()
            today_in, today_out, today_count = row
        # Last 7 days
        async with db.execute(
            "SELECT COALESCE(SUM(input_tokens),0), COALESCE(SUM(output_tokens),0), COUNT(*) FROM usage_log WHERE created_at >= ?",
            (week_ago,)
        ) as cur:
            row = await cur.fetchone()
            week_in, week_out, week_count = row
        # All time
        async with db.execute(
            "SELECT COALESCE(SUM(input_tokens),0), COALESCE(SUM(output_tokens),0), COUNT(*) FROM usage_log"
        ) as cur:
            row = await cur.fetchone()
            all_in, all_out, all_count = row
        return {
            "today": {"input_tokens": today_in, "output_tokens": today_out, "requests": today_count, "total_tokens": today_in + today_out},
            "last_7_days": {"input_tokens": week_in, "output_tokens": week_out, "requests": week_count, "total_tokens": week_in + week_out},
            "all_time": {"input_tokens": all_in, "output_tokens": all_out, "requests": all_count, "total_tokens": all_in + all_out},
        }


async def list_tasks(limit: int = 50) -> list:
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            "SELECT * FROM tasks ORDER BY created_at DESC LIMIT ?", (limit,)
        ) as cur:
            return [dict(r) for r in await cur.fetchall()]


async def cancel_task(task_id: str) -> bool:
    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute(
            "UPDATE tasks SET status='cancelled' WHERE task_id=? AND status='pending'",
            (task_id,),
        )
        await db.commit()
        return cur.rowcount > 0


async def _run_task(task_id: str, prompt: str, run_fn, skills: list[str] | None = None, context_id: str | None = None):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("UPDATE tasks SET status='running' WHERE task_id=?", (task_id,))
        await db.commit()

    result_parts, in_tok, out_tok, status = [], 0, 0, "done"
    _final_start = 0
    _pane_data = None  # capture last pane signal for "View in chat" replay
    try:
        async for chunk in run_fn(prompt, skills=skills):
            if chunk.startswith("data: ") and not chunk.startswith("data: [DONE]"):
                try:
                    msg = json.loads(chunk[6:])
                    # A completed tool round means everything streamed so far was
                    # narration/tool-data, not the answer — discard it so the
                    # stored result is only the final post-tool text. (Fixes raw
                    # "[Data from read_calendar]: {...}" leaking into briefings.)
                    if msg.get("phase") == "tool_round":
                        result_parts = []
                    if msg.get("phase") == "final":
                        _final_start = len(result_parts)
                    if "token" in msg:
                        result_parts.append(msg["token"])
                    if "text" in msg:
                        result_parts.append(msg["text"])
                    if "usage" in msg:
                        in_tok = msg["usage"].get("input_tokens", 0)
                        out_tok = msg["usage"].get("output_tokens", 0)
                    # Forward pane signals (compose panes) to frontend via notification queue
                    if "pane" in msg:
                        _pane_data = {"pane": msg["pane"], "paneData": msg.get("paneData", {})}
                        try:
                            import shared
                            shared.notify_all({"type": "pane_signal", **_pane_data})
                        except Exception:
                            pass
                except Exception:
                    pass
    except Exception as exc:
        status = "failed"
        result_parts = [f"Error: {exc}"]

    # result_parts holds only the final post-tool answer: every completed tool
    # round resets it (phase:tool_round above), so intermediate narration / raw
    # "[Data from ...]" blocks never survive into the stored result.
    result_text = "".join(result_parts)

    # Seed conversation_store so "view this chat" follow-ups have server-side history.
    if context_id and result_text:
        try:
            import shared as _shared
            await _shared.conversation_store.append(context_id, [
                {"role": "user", "content": prompt},
                {"role": "assistant", "content": result_text},
            ])
        except Exception:
            pass

    done_at = datetime.now(timezone.utc).isoformat()
    pane_json = json.dumps(_pane_data) if _pane_data else None
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "UPDATE tasks SET status=?, completed_at=?, result=?, input_tokens=?, output_tokens=?, pane_data=? WHERE task_id=?",
            (status, done_at, result_text, in_tok, out_tok, pane_json, task_id),
        )
        await db.commit()

    # Log usage for background tasks
    try:
        await log_usage("background", (prompt or "")[:100], in_tok, out_tok)
    except Exception:
        pass

    if _notify_callback:
        try:
            # Show the END of the result (the actual answer), not the beginning (the plan)
            _summary = result_text.strip()[-200:] if len(result_text) > 200 else result_text
            await _notify_callback(task_id, _summary, status, in_tok, out_tok)
        except Exception:
            pass


async def worker(run_fn):
    while True:
        try:
            async with aiosqlite.connect(DB_PATH) as db:
                db.row_factory = aiosqlite.Row
                async with db.execute(
                    "SELECT task_id, prompt, skills, context_id FROM tasks WHERE status='pending' ORDER BY created_at LIMIT 1"
                ) as cur:
                    row = await cur.fetchone()
            if row:
                skills = json.loads(row["skills"] or "[]") if row["skills"] else []
                await _run_task(row["task_id"], row["prompt"], run_fn, skills=skills, context_id=row["context_id"])
            else:
                await asyncio.sleep(2)
        except Exception:
            await asyncio.sleep(5)


async def start_worker(run_fn):
    global _worker_task
    if _worker_task and not _worker_task.done():
        return  # already running — guard against duplicate lifespan calls
    await init_db()
    _worker_task = asyncio.create_task(worker(run_fn))


async def stop_worker():
    global _worker_task
    if _worker_task:
        _worker_task.cancel()
        try:
            await _worker_task
        except asyncio.CancelledError:
            pass
        _worker_task = None
