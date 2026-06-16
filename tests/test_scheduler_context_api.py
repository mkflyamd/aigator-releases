"""Tests for context_id surfacing through the HTTP API layer.

Verifies that:
1. GET /api/tasks/{task_id} includes context_id in its JSON response.
2. GET /api/scheduler/jobs/{job_id} includes context_id on the last_run entry
   so the frontend can route "view this chat" to the right conversation.
"""
import asyncio
import json
import uuid
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient


# ── fixtures ──────────────────────────────────────────────────────────────────

@pytest.fixture()
def task_db(tmp_path, monkeypatch):
    """Point task_queue at a fresh temp DB for each test."""
    import task_queue as tq
    db = tmp_path / "tasks.db"
    monkeypatch.setattr(tq, "DB_PATH", db)
    asyncio.new_event_loop().run_until_complete(tq.init_db())
    return db


@pytest.fixture()
def tasks_client(task_db):
    from routes.tasks import router
    app = FastAPI()
    app.include_router(router)
    return TestClient(app)


@pytest.fixture()
def sched_db(tmp_path, monkeypatch):
    """Point scheduler at a fresh temp DB and seed job_meta + job_history."""
    import scheduler as sched
    db = tmp_path / "scheduler.db"
    monkeypatch.setattr(sched, "DB_PATH", db)
    return db


# ── Task API tests ─────────────────────────────────────────────────────────────

class TestTasksApiExposesContextId:
    """GET /api/tasks/{task_id} must include context_id in JSON."""

    def test_get_task_returns_context_id(self, task_db, tasks_client):
        import task_queue as tq
        job_id = str(uuid.uuid4())
        task_id = asyncio.new_event_loop().run_until_complete(
            tq.enqueue("do the thing", context_id=job_id)
        )

        resp = tasks_client.get(f"/api/tasks/{task_id}")

        assert resp.status_code == 200
        body = resp.json()
        assert "context_id" in body
        assert body["context_id"] == job_id

    def test_get_task_context_id_is_null_when_not_set(self, task_db, tasks_client):
        import task_queue as tq
        task_id = asyncio.new_event_loop().run_until_complete(
            tq.enqueue("interactive chat task")
        )

        resp = tasks_client.get(f"/api/tasks/{task_id}")

        assert resp.status_code == 200
        body = resp.json()
        assert "context_id" in body
        assert body["context_id"] is None


# ── Scheduler API tests ────────────────────────────────────────────────────────

class TestSchedulerJobHistoryExposesContextId:
    """GET /api/scheduler/jobs/{job_id} last_run must include context_id == job_id."""

    def _seed_job_and_task(self, tmp_path, sched_db, task_db, monkeypatch):
        import task_queue as tq
        import scheduler as sched
        import aiosqlite

        job_id = str(uuid.uuid4())

        async def _setup():
            # Seed job_meta and job_history
            import aiosqlite as _aio
            async with _aio.connect(sched_db) as db:
                await db.execute(sched._DDL_JOB_META)
                await db.execute(sched._DDL_JOB_HISTORY)
                await db.execute(
                    "INSERT INTO job_meta (job_id, name, prompt, trigger_type, trigger_args, token_budget, skills, created_at) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                    (job_id, "Weekly report", "write the weekly report", "interval",
                     json.dumps({"weeks": 1}), 0, "[]", "2026-05-26T00:00:00+00:00"),
                )
                await db.commit()

            # Enqueue a task as the scheduler would
            task_id = await tq.enqueue("write the weekly report", context_id=job_id)

            async with _aio.connect(sched_db) as db:
                await db.execute(
                    "INSERT INTO job_history (job_id, task_id, started_at, status) VALUES (?, ?, ?, ?)",
                    (job_id, task_id, "2026-05-26T08:00:00+00:00", "done"),
                )
                await db.commit()

            return job_id, task_id

        return asyncio.new_event_loop().run_until_complete(_setup())

    def test_get_job_last_run_includes_context_id(self, tmp_path, sched_db, task_db, monkeypatch):
        import scheduler as sched

        # Patch APScheduler so get_job returns None (avoids scheduler init)
        monkeypatch.setattr(sched._scheduler, "get_job", lambda jid: None)

        job_id, task_id = self._seed_job_and_task(tmp_path, sched_db, task_db, monkeypatch)

        from routes.scheduler import router
        app = FastAPI()
        app.include_router(router)
        client = TestClient(app)

        resp = client.get(f"/api/scheduler/jobs/{job_id}")

        assert resp.status_code == 200
        body = resp.json()
        assert "history" in body
        assert len(body["history"]) >= 1
        last = body["history"][0]
        assert "context_id" in last, "history entry must include context_id"
        assert last["context_id"] == job_id
