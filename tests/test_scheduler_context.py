"""Tests for scheduled-job context_id plumbing.

Hypothesis being verified: when a scheduled agent job fires (or is
triggered via run-now), the resulting task row must carry a stable
context_id equal to the job_id so that "view this chat" can route the
user into the correct conversation context.
"""
import asyncio
import json
import uuid
from pathlib import Path

import pytest
import aiosqlite


# ── helpers ──────────────────────────────────────────────────────────────────

def _fresh_db(tmp_path: Path) -> Path:
    return tmp_path / "tasks_test.db"


async def _init_and_enqueue(db_path, prompt, skills=None, context_id=None):
    import task_queue as tq
    original = tq.DB_PATH
    tq.DB_PATH = db_path
    try:
        await tq.init_db()
        task_id = await tq.enqueue(prompt, skills=skills, context_id=context_id)
        return task_id
    finally:
        tq.DB_PATH = original


async def _get_task(db_path, task_id):
    import task_queue as tq
    original = tq.DB_PATH
    tq.DB_PATH = db_path
    try:
        return await tq.get_task(task_id)
    finally:
        tq.DB_PATH = original


# ── tests ─────────────────────────────────────────────────────────────────────

class TestEnqueueAcceptsContextId:
    """task_queue.enqueue must accept and persist a context_id."""

    def test_enqueue_stores_context_id(self, tmp_path):
        db_path = _fresh_db(tmp_path)
        context_id = f"job-{uuid.uuid4()}"

        task_id = asyncio.new_event_loop().run_until_complete(
            _init_and_enqueue(db_path, "do something", context_id=context_id)
        )

        async def _read():
            async with aiosqlite.connect(db_path) as db:
                db.row_factory = aiosqlite.Row
                async with db.execute(
                    "SELECT context_id FROM tasks WHERE task_id = ?", (task_id,)
                ) as cur:
                    row = await cur.fetchone()
            return dict(row) if row else None

        row = asyncio.new_event_loop().run_until_complete(_read())
        assert row is not None
        assert row["context_id"] == context_id

    def test_enqueue_without_context_id_stores_null(self, tmp_path):
        db_path = _fresh_db(tmp_path)

        task_id = asyncio.new_event_loop().run_until_complete(
            _init_and_enqueue(db_path, "do something")
        )

        async def _read():
            async with aiosqlite.connect(db_path) as db:
                db.row_factory = aiosqlite.Row
                async with db.execute(
                    "SELECT context_id FROM tasks WHERE task_id = ?", (task_id,)
                ) as cur:
                    row = await cur.fetchone()
            return dict(row) if row else None

        row = asyncio.new_event_loop().run_until_complete(_read())
        assert row is not None
        assert row["context_id"] is None


class TestGetTaskReturnsContextId:
    """get_task must include context_id in the returned dict."""

    def test_get_task_returns_context_id(self, tmp_path):
        db_path = _fresh_db(tmp_path)
        context_id = f"job-{uuid.uuid4()}"

        async def _run():
            task_id = await _init_and_enqueue(db_path, "hello", context_id=context_id)
            return await _get_task(db_path, task_id)

        task = asyncio.new_event_loop().run_until_complete(_run())
        assert task is not None
        assert "context_id" in task
        assert task["context_id"] == context_id


class TestSchedulerPassesJobIdAsContextId:
    """Scheduler must pass job_id as context_id when enqueueing a task."""

    def test_execute_job_uses_job_id_as_context_id(self, tmp_path, monkeypatch):
        """_execute_job must call task_queue.enqueue(context_id=job_id)."""
        import task_queue as tq
        import scheduler as sched

        db_path = _fresh_db(tmp_path)
        monkeypatch.setattr(tq, "DB_PATH", db_path)

        # Patch scheduler DB path and pre-seed job_meta
        sched_db = tmp_path / "scheduler_test.db"
        monkeypatch.setattr(sched, "DB_PATH", sched_db)

        job_id = str(uuid.uuid4())

        async def _setup_and_run():
            # Bootstrap task DB
            await tq.init_db()

            # Seed job_meta directly (skip APScheduler)
            async with aiosqlite.connect(sched_db) as db:
                await db.execute(sched._DDL_JOB_META)
                await db.execute(sched._DDL_JOB_HISTORY)
                await db.execute(
                    "INSERT INTO job_meta (job_id, name, prompt, trigger_type, trigger_args, token_budget, skills, created_at) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                    (job_id, "test job", "write a report", "interval",
                     json.dumps({"seconds": 60}), 0, "[]",
                     "2026-05-26T00:00:00+00:00"),
                )
                await db.commit()

            await sched._execute_job(job_id)

            # Fetch the task that was enqueued
            async with aiosqlite.connect(db_path) as db:
                db.row_factory = aiosqlite.Row
                async with db.execute(
                    "SELECT context_id FROM tasks ORDER BY created_at DESC LIMIT 1"
                ) as cur:
                    row = await cur.fetchone()
            return dict(row) if row else None

        row = asyncio.new_event_loop().run_until_complete(_setup_and_run())
        assert row is not None, "No task was enqueued by _execute_job"
        assert row["context_id"] == job_id

    def test_run_job_now_uses_job_id_as_context_id(self, tmp_path, monkeypatch):
        """run_job_now must call task_queue.enqueue(context_id=job_id)."""
        import task_queue as tq
        import scheduler as sched

        db_path = _fresh_db(tmp_path)
        monkeypatch.setattr(tq, "DB_PATH", db_path)

        sched_db = tmp_path / "scheduler_test.db"
        monkeypatch.setattr(sched, "DB_PATH", sched_db)

        job_id = str(uuid.uuid4())

        async def _setup_and_run():
            await tq.init_db()

            async with aiosqlite.connect(sched_db) as db:
                await db.execute(sched._DDL_JOB_META)
                await db.execute(sched._DDL_JOB_HISTORY)
                await db.execute(
                    "INSERT INTO job_meta (job_id, name, prompt, trigger_type, trigger_args, token_budget, skills, created_at) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                    (job_id, "test job", "publish the update", "interval",
                     json.dumps({"seconds": 60}), 0, "[]",
                     "2026-05-26T00:00:00+00:00"),
                )
                await db.commit()

            returned_task_id = await sched.run_job_now(job_id)

            async with aiosqlite.connect(db_path) as db:
                db.row_factory = aiosqlite.Row
                async with db.execute(
                    "SELECT context_id FROM tasks WHERE task_id = ?", (returned_task_id,)
                ) as cur:
                    row = await cur.fetchone()
            return dict(row) if row else None

        row = asyncio.new_event_loop().run_until_complete(_setup_and_run())
        assert row is not None
        assert row["context_id"] == job_id
