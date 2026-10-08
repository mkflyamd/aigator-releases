"""Tests for task_drafts.py — the durable, task-bound draft mirror (issue #54).

Covers the module in isolation (no HTTP layer): table creation, recording,
status sync, list-for-task with expiry flagging, and the rehydrate-data
reader. See test_task_drafts_hitl.py for the routes/drafts.py integration
(rehydration into _pending_drafts + approve/open-in-outlook status sync).
"""
import asyncio
from datetime import datetime, timedelta, timezone

import pytest


def _fresh_db(tmp_path):
    return tmp_path / "tasks_drafts_test.db"


def _run(coro):
    return asyncio.new_event_loop().run_until_complete(coro)


@pytest.fixture
def td(tmp_path, monkeypatch):
    import task_drafts as _td

    monkeypatch.setattr(_td, "DB_PATH", _fresh_db(tmp_path))
    _run(_td.init_table())
    return _td


def test_record_and_list_for_task(td):
    _run(td.record_draft(
        "task-1", "draft-1", "email-send",
        {"draft_id": "draft-1", "to": "bob@amd.com"},
        {"to": "bob@amd.com", "message": "hi"},
    ))
    drafts = _run(td.list_for_task("task-1"))
    assert len(drafts) == 1
    assert drafts[0]["draft_id"] == "draft-1"
    assert drafts[0]["draft_type"] == "email-send"
    assert drafts[0]["status"] == "pending"
    assert drafts[0]["draft_data"] == {"draft_id": "draft-1", "to": "bob@amd.com"}
    assert "params" not in drafts[0], "list_for_task must never leak the mutation payload"
    assert drafts[0]["expired"] is False


def test_list_for_task_multiple_drafts_one_task(td):
    """Acceptance criteria: multiple drafts from one task must all surface."""
    _run(td.record_draft("task-1", "draft-a", "email-send", {"draft_id": "draft-a"}, {}))
    _run(td.record_draft("task-1", "draft-b", "slack-post", {"draft_id": "draft-b"}, {}))
    drafts = _run(td.list_for_task("task-1"))
    assert {d["draft_id"] for d in drafts} == {"draft-a", "draft-b"}


def test_list_for_task_scoped_to_task_id(td):
    _run(td.record_draft("task-1", "draft-a", "email-send", {"draft_id": "draft-a"}, {}))
    _run(td.record_draft("task-2", "draft-b", "email-send", {"draft_id": "draft-b"}, {}))
    assert [d["draft_id"] for d in _run(td.list_for_task("task-1"))] == ["draft-a"]
    assert [d["draft_id"] for d in _run(td.list_for_task("task-2"))] == ["draft-b"]


def test_sync_status_updates_existing_row(td):
    _run(td.record_draft("task-1", "draft-1", "email-send", {"draft_id": "draft-1"}, {}))
    _run(td.sync_status("draft-1", "sending"))
    drafts = _run(td.list_for_task("task-1"))
    assert drafts[0]["status"] == "sending"


def test_sync_status_on_unknown_draft_is_a_harmless_noop(td):
    """A plain interactive-chat draft never has a task_drafts row at all —
    sync_status must not raise just because nothing matched."""
    _run(td.sync_status("never-recorded", "sending"))  # must not raise


def test_get_for_rehydrate_includes_params(td):
    _run(td.record_draft(
        "task-1", "draft-1", "email-send",
        {"draft_id": "draft-1"},
        {"to": "bob@amd.com", "message": "the real payload"},
    ))
    row = _run(td.get_for_rehydrate("draft-1"))
    assert row["params"] == {"to": "bob@amd.com", "message": "the real payload"}
    assert row["draft_type"] == "email-send"
    assert row["expired"] is False


def test_get_for_rehydrate_unknown_returns_none(td):
    assert _run(td.get_for_rehydrate("nope")) is None


def test_expired_flag_true_past_ttl(td, monkeypatch):
    import task_drafts as _td

    monkeypatch.setattr(_td, "TASK_DRAFT_TTL_SECONDS", 60)
    old_iso = (datetime.now(timezone.utc) - timedelta(seconds=120)).isoformat()
    _run(td.record_draft("task-1", "draft-1", "email-send", {"draft_id": "draft-1"}, {}))
    # record_draft always stamps "now" — directly backdate created_at to simulate age.
    import aiosqlite

    async def _backdate():
        async with aiosqlite.connect(_td.DB_PATH) as db:
            await db.execute(
                "UPDATE task_drafts SET created_at=? WHERE draft_id='draft-1'", (old_iso,)
            )
            await db.commit()

    _run(_backdate())
    drafts = _run(td.list_for_task("task-1"))
    assert drafts[0]["expired"] is True
    row = _run(td.get_for_rehydrate("draft-1"))
    assert row["expired"] is True


def test_expired_flag_false_within_ttl(td):
    _run(td.record_draft("task-1", "draft-1", "email-send", {"draft_id": "draft-1"}, {}))
    drafts = _run(td.list_for_task("task-1"))
    assert drafts[0]["expired"] is False


def test_sent_status_is_terminal_marker_after_pop(td):
    """pop_draft() deletes the in-memory record entirely — the durable row
    (marked "sent") becomes the only remaining evidence for a task opened
    again later."""
    _run(td.record_draft("task-1", "draft-1", "email-send", {"draft_id": "draft-1"}, {}))
    _run(td.sync_status("draft-1", "sending"))
    _run(td.sync_status("draft-1", "sent"))
    drafts = _run(td.list_for_task("task-1"))
    assert drafts[0]["status"] == "sent"
    assert drafts[0]["expired"] is False, "a sent draft is never 'expired' regardless of age"
