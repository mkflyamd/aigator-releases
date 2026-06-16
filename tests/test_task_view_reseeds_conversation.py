"""Tests that GET /api/tasks/{task_id} re-seeds conversation_store
when the store is empty for that context_id.

This covers:
- Server restart (in-memory store wiped)
- User closing the tab (DELETE /api/conversation/{id} clears the store)

In both cases, the next "view this chat" click must restore context.
"""
import asyncio
import uuid
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient


@pytest.fixture()
def task_db(tmp_path, monkeypatch):
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


class TestGetTaskReseedsConversation:
    """GET /api/tasks/{task_id} must re-seed conversation_store when empty."""

    def test_view_task_seeds_empty_store_after_restart(self, task_db, tasks_client, monkeypatch):
        """Simulates server restart: store is empty, viewing the task re-seeds it."""
        import task_queue as tq
        import shared as sh

        context_id = str(uuid.uuid4())
        prompt = "write the quarterly review"
        result_text = "Here is the quarterly review draft..."

        # Enqueue and simulate completed task with result
        async def _setup():
            task_id = await tq.enqueue(prompt, context_id=context_id)
            # Manually write result (bypass run_fn for simplicity)
            import aiosqlite
            async with aiosqlite.connect(task_db) as db:
                await db.execute(
                    "UPDATE tasks SET status='done', result=? WHERE task_id=?",
                    (result_text, task_id)
                )
                await db.commit()
            return task_id

        task_id = asyncio.new_event_loop().run_until_complete(_setup())

        # Simulate restart: store is empty
        assert not sh.conversation_store.has(context_id)

        # Act: user clicks "view this chat" → GET /api/tasks/{task_id}
        resp = tasks_client.get(f"/api/tasks/{task_id}")
        assert resp.status_code == 200

        # Assert: store is now seeded
        assert sh.conversation_store.has(context_id), \
            "GET /api/tasks should seed conversation_store when empty"

        history = asyncio.new_event_loop().run_until_complete(
            sh.conversation_store.get_window(context_id)
        )
        assert len(history) == 2
        assert history[0]["role"] == "user"
        assert history[0]["content"] == prompt
        assert history[1]["role"] == "assistant"
        assert result_text in history[1]["content"]

    def test_view_task_seeds_after_tab_close_wipes_store(self, task_db, tasks_client, monkeypatch):
        """Simulates user closing the tab: store deleted, viewing re-seeds it."""
        import task_queue as tq
        import shared as sh

        context_id = str(uuid.uuid4())
        prompt = "generate weekly status"
        result_text = "Weekly status: all systems nominal."

        async def _setup():
            task_id = await tq.enqueue(prompt, context_id=context_id)
            import aiosqlite
            async with aiosqlite.connect(task_db) as db:
                await db.execute(
                    "UPDATE tasks SET status='done', result=? WHERE task_id=?",
                    (result_text, task_id)
                )
                await db.commit()
            # Seed then delete (simulates tab close)
            await sh.conversation_store.append(context_id, [
                {"role": "user", "content": prompt},
                {"role": "assistant", "content": result_text},
            ])
            await sh.conversation_store.delete(context_id)
            return task_id

        task_id = asyncio.new_event_loop().run_until_complete(_setup())
        assert not sh.conversation_store.has(context_id)

        # Act: user opens "view this chat" again after closing tab
        resp = tasks_client.get(f"/api/tasks/{task_id}")
        assert resp.status_code == 200

        assert sh.conversation_store.has(context_id), \
            "GET /api/tasks should re-seed after tab close wiped the store"

    def test_view_task_does_not_reseed_when_store_already_populated(self, task_db, tasks_client):
        """Existing conversation history must not be overwritten on GET /api/tasks."""
        import task_queue as tq
        import shared as sh

        context_id = str(uuid.uuid4())
        prompt = "summarise meeting notes"
        result_text = "Meeting summary: decisions were made."
        follow_up = "Can you bullet-point the action items?"

        async def _setup():
            task_id = await tq.enqueue(prompt, context_id=context_id)
            import aiosqlite
            async with aiosqlite.connect(task_db) as db:
                await db.execute(
                    "UPDATE tasks SET status='done', result=? WHERE task_id=?",
                    (result_text, task_id)
                )
                await db.commit()
            # Pre-seed with existing conversation (includes follow-up)
            await sh.conversation_store.append(context_id, [
                {"role": "user", "content": prompt},
                {"role": "assistant", "content": result_text},
                {"role": "user", "content": follow_up},
            ])
            return task_id

        task_id = asyncio.new_event_loop().run_until_complete(_setup())

        resp = tasks_client.get(f"/api/tasks/{task_id}")
        assert resp.status_code == 200

        history = asyncio.new_event_loop().run_until_complete(
            sh.conversation_store.get_window(context_id)
        )
        # Must still have 3 turns — not overwritten back to 2
        assert len(history) == 3, \
            f"Existing conversation must not be overwritten, got {len(history)} turns"
        assert history[2]["content"] == follow_up

    def test_view_task_without_context_id_does_not_seed(self, task_db, tasks_client):
        """Interactive tasks (no context_id) must not touch conversation_store."""
        import task_queue as tq
        import shared as sh

        store_keys_before = set(sh.conversation_store._store.keys())

        async def _setup():
            task_id = await tq.enqueue("just a chat", context_id=None)
            import aiosqlite
            async with aiosqlite.connect(task_db) as db:
                await db.execute(
                    "UPDATE tasks SET status='done', result='answer' WHERE task_id=?",
                    (task_id,)
                )
                await db.commit()
            return task_id

        task_id = asyncio.new_event_loop().run_until_complete(_setup())
        tasks_client.get(f"/api/tasks/{task_id}")

        new_keys = set(sh.conversation_store._store.keys()) - store_keys_before
        assert not new_keys, f"Unexpected store keys added for no-context_id task: {new_keys}"
