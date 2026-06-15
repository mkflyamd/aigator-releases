"""Tests that _run_task seeds conversation_store with prompt+result
when the task has a context_id, so follow-up messages in "view this chat"
have server-side history to work with.
"""
import asyncio
import json
import uuid
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest


# ── helpers ───────────────────────────────────────────────────────────────────

def _fresh_db(tmp_path: Path) -> Path:
    return tmp_path / "tasks.db"


async def _enqueue_with_context(db_path, prompt, context_id):
    import task_queue as tq
    tq.DB_PATH = db_path
    await tq.init_db()
    return await tq.enqueue(prompt, context_id=context_id)


def _make_run_fn(response_text: str):
    """Minimal async generator that yields a single assistant response."""
    async def _run_fn(prompt, skills=None):
        yield f'data: {json.dumps({"text": response_text})}\n\n'
        yield 'data: [DONE]\n\n'
    return _run_fn


# ── tests ─────────────────────────────────────────────────────────────────────

class TestRunTaskSeedsConversationStore:
    """After _run_task completes, conversation_store[context_id] must contain
    the prompt (as user turn) and the result (as assistant turn)."""

    def test_run_task_seeds_conversation_when_context_id_set(self, tmp_path, monkeypatch):
        import task_queue as tq
        import shared as sh

        db_path = _fresh_db(tmp_path)
        monkeypatch.setattr(tq, "DB_PATH", db_path)

        context_id = str(uuid.uuid4())
        prompt = "write the weekly status update"
        response = "Here is the weekly status update..."

        async def _run():
            await tq.init_db()
            task_id = await tq.enqueue(prompt, context_id=context_id)
            await tq._run_task(task_id, prompt, _make_run_fn(response), context_id=context_id)
            return await sh.conversation_store.get_window(context_id)

        history = asyncio.new_event_loop().run_until_complete(_run())

        assert len(history) == 2, f"Expected 2 turns (user+assistant), got {len(history)}: {history}"
        assert history[0]["role"] == "user"
        assert history[0]["content"] == prompt
        assert history[1]["role"] == "assistant"
        assert response in history[1]["content"]

    def test_run_task_does_not_seed_when_no_context_id(self, tmp_path, monkeypatch):
        import task_queue as tq
        import shared as sh

        db_path = _fresh_db(tmp_path)
        monkeypatch.setattr(tq, "DB_PATH", db_path)

        prompt = "interactive chat"
        response = "Here is my answer"
        store_before = set(sh.conversation_store._store.keys())

        async def _run():
            await tq.init_db()
            task_id = await tq.enqueue(prompt)
            await tq._run_task(task_id, prompt, _make_run_fn(response), context_id=None)

        asyncio.new_event_loop().run_until_complete(_run())

        new_keys = set(sh.conversation_store._store.keys()) - store_before
        assert not new_keys, f"conversation_store gained keys with no context_id: {new_keys}"

    def test_worker_picks_up_context_id_from_db(self, tmp_path, monkeypatch):
        """Worker SELECT must include context_id so it reaches _run_task."""
        import task_queue as tq

        db_path = _fresh_db(tmp_path)
        monkeypatch.setattr(tq, "DB_PATH", db_path)

        context_id = str(uuid.uuid4())
        captured = {}

        async def _fake_run_task(task_id, prompt, run_fn, skills=None, context_id=None):
            captured["context_id"] = context_id

        monkeypatch.setattr(tq, "_run_task", _fake_run_task)

        async def _run():
            await tq.init_db()
            await tq.enqueue("do work", context_id=context_id)
            # Run worker for one iteration then stop
            try:
                await asyncio.wait_for(tq.worker(_make_run_fn("done")), timeout=3)
            except asyncio.TimeoutError:
                pass

        asyncio.new_event_loop().run_until_complete(_run())

        assert "context_id" in captured, "worker never called _run_task"
        assert captured["context_id"] == context_id
