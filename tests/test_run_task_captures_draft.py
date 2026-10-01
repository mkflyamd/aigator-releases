"""_run_task must capture a "draft" SSE signal and persist it durably keyed
by task_id (issue #54) — before this fix, only "pane" signals were handled;
a scheduled job's draft was silently created in skills._drafts._pending_drafts
(same tool-dispatch path as interactive chat) but never surfaced anywhere,
so it just expired 30 minutes later, unreachable by any tab.
"""
import asyncio
import json
import uuid
from pathlib import Path

import pytest


def _fresh_db(tmp_path: Path) -> Path:
    return tmp_path / "tasks.db"


def _run_coro(coro):
    return asyncio.new_event_loop().run_until_complete(coro)


def _make_draft_run_fn(draft_type: str, draft_data: dict, final_text: str = "Draft ready."):
    async def _run_fn(prompt, skills=None):
        yield f"data: {json.dumps({'draft': draft_type, 'draftData': draft_data})}\n\n"
        yield f"data: {json.dumps({'text': final_text})}\n\n"
        yield "data: [DONE]\n\n"

    return _run_fn


@pytest.fixture
def env(tmp_path, monkeypatch):
    import task_queue as tq
    import task_drafts as td

    db_path = _fresh_db(tmp_path)
    monkeypatch.setattr(tq, "DB_PATH", db_path)
    monkeypatch.setattr(td, "DB_PATH", db_path)
    _run_coro(tq.init_db())
    return tq, td


def test_run_task_persists_draft_signal(env, monkeypatch):
    tq, td = env
    from skills import _drafts

    draft_id = _drafts.create_draft(
        "email-send", {"to": "bob@amd.com", "message": "hi"}, {}
    )

    async def _run():
        task_id = await tq.enqueue("send bob a note")
        await tq._run_task(
            task_id, "send bob a note",
            _make_draft_run_fn("email-send", {"draft_id": draft_id, "to": "bob@amd.com"}),
        )
        return task_id

    task_id = _run_coro(_run())

    drafts = _run_coro(td.list_for_task(task_id))
    assert len(drafts) == 1
    assert drafts[0]["draft_id"] == draft_id
    assert drafts[0]["draft_type"] == "email-send"
    assert drafts[0]["status"] == "pending"
    assert drafts[0]["draft_data"]["to"] == "bob@amd.com"

    # The mutation payload must have been captured too (from the live
    # _pending_drafts entry at the moment the SSE chunk was processed) —
    # required for restart-recovery rehydration, not just display.
    row = _run_coro(td.get_for_rehydrate(draft_id))
    assert row["params"] == {"to": "bob@amd.com", "message": "hi"}


def test_run_task_ignores_draft_signal_missing_draft_id(env):
    """A draftData payload with no draft_id (shouldn't happen in practice,
    but defensively) must not raise or create a garbage row."""
    tq, td = env

    async def _run():
        task_id = await tq.enqueue("do something")
        await tq._run_task(
            task_id, "do something",
            _make_draft_run_fn("email-send", {"to": "bob@amd.com"}),  # no draft_id key
        )
        return task_id

    task_id = _run_coro(_run())
    assert _run_coro(td.list_for_task(task_id)) == []


def test_run_task_still_produces_result_text_alongside_draft(env):
    """Capturing the draft signal must not regress the existing result-text
    capture — the task's own result column should still be populated."""
    tq, td = env
    from skills import _drafts

    draft_id = _drafts.create_draft("email-send", {"to": "a@b.com"}, {})

    async def _run():
        task_id = await tq.enqueue("draft an email")
        await tq._run_task(
            task_id, "draft an email",
            _make_draft_run_fn("email-send", {"draft_id": draft_id}, final_text="Here's the draft."),
        )
        return await tq.get_task(task_id)

    task = _run_coro(_run())
    assert task["result"] == "Here's the draft."
    assert task["status"] == "done"


def test_multiple_drafts_from_one_task_both_persisted(env):
    """Acceptance criteria: multiple drafts from one task must all surface."""
    tq, td = env
    from skills import _drafts

    d1 = _drafts.create_draft("email-send", {"to": "a@b.com"}, {})
    d2 = _drafts.create_draft("slack-post", {"channel_id": "C1", "message": "hi"}, {})

    async def _run_fn(prompt, skills=None):
        yield f"data: {json.dumps({'draft': 'email-send', 'draftData': {'draft_id': d1}})}\n\n"
        yield f"data: {json.dumps({'draft': 'slack-post', 'draftData': {'draft_id': d2}})}\n\n"
        yield "data: [DONE]\n\n"

    async def _run():
        task_id = await tq.enqueue("do two things")
        await tq._run_task(task_id, "do two things", _run_fn)
        return task_id

    task_id = _run_coro(_run())
    drafts = _run_coro(td.list_for_task(task_id))
    assert {d["draft_id"] for d in drafts} == {d1, d2}
