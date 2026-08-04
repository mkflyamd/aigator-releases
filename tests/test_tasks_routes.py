"""Tests for background task queue routes."""

import asyncio

import aiosqlite
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient


@pytest.fixture()
def task_db(tmp_path, monkeypatch):
    import task_queue as tq

    db_path = tmp_path / "tasks.db"
    monkeypatch.setattr(tq, "DB_PATH", db_path)
    asyncio.run(tq.init_db())
    return db_path


@pytest.fixture()
def tasks_client(task_db):
    from routes.tasks import router

    app = FastAPI()
    app.include_router(router)
    return TestClient(app)


def test_clear_completed_tasks_preserves_active_tasks(task_db, tasks_client):
    import task_queue as tq

    async def setup_tasks():
        done_id = await tq.enqueue("done task")
        failed_id = await tq.enqueue("failed task")
        pending_id = await tq.enqueue("pending task")
        async with aiosqlite.connect(task_db) as db:
            await db.execute("UPDATE tasks SET status = 'done' WHERE task_id = ?", (done_id,))
            await db.execute("UPDATE tasks SET status = 'failed' WHERE task_id = ?", (failed_id,))
            await db.commit()
        return pending_id

    pending_id = asyncio.run(setup_tasks())

    response = tasks_client.delete("/api/tasks/completed")

    assert response.status_code == 200
    assert response.json() == {"deleted": 2}
    remaining = tasks_client.get("/api/tasks").json()
    assert [(task["task_id"], task["status"]) for task in remaining] == [
        (pending_id, "pending")
    ]
