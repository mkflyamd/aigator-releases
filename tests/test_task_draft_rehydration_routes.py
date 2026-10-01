"""Integration tests for issue #54's approve/open-in-outlook wiring:

  - A live draft's status transitions must mirror into the durable
    task_drafts table (so a task opened again later shows "sent" instead
    of just vanishing).
  - A draft missing from the in-memory _pending_drafts store (simulating a
    backend restart) must be rehydrated from a fresh, still-"pending"
    durable row and remain approvable.
  - An expired durable row must NOT be rehydrated — approve must behave
    exactly as if the draft never existed (404).
  - GET /api/tasks/{task_id} must return the drafts array.
"""
import asyncio
from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from app import app
from skills import _drafts


def _csrf():
    from security import get_csrf_token
    return get_csrf_token()


def _approve(client, draft_id, body=None):
    return client.post(
        f"/api/drafts/{draft_id}/approve",
        headers={"X-CSRF-Token": _csrf()},
        json=body,
    )


def _gc_for_send():
    gc = MagicMock()
    gc.post.return_value = {"id": "SENTOK"}
    return gc


def setup_function(function):
    _drafts._pending_drafts.clear()


def _run(coro):
    return asyncio.new_event_loop().run_until_complete(coro)


@pytest.fixture
def td(tmp_path, monkeypatch):
    import task_drafts as _td

    monkeypatch.setattr(_td, "DB_PATH", tmp_path / "tasks.db")
    _run(_td.init_table())
    return _td


class TestStatusSyncOnApprove:
    def test_approve_success_syncs_sent_status(self, td):
        client = TestClient(app)
        draft_id = _drafts.create_draft(
            "email-send", {"to": "bob@amd.com", "message": "hi"}, {}
        )
        _run(td.record_draft("task-1", draft_id, "email-send", {"draft_id": draft_id}, {}))

        with patch("skills._m365.helpers.get_graph_client", return_value=_gc_for_send()):
            r = _approve(client, draft_id)
        assert r.status_code == 200, r.text

        drafts = _run(td.list_for_task("task-1"))
        assert drafts[0]["status"] == "sent"

    def test_approve_failure_syncs_pending_status_for_retry(self, td):
        client = TestClient(app)
        draft_id = _drafts.create_draft(
            "email-send", {"to": "", "message": "hi"}, {}
        )  # no recipients -> 400 inside approve_draft, before any Graph call
        _run(td.record_draft("task-1", draft_id, "email-send", {"draft_id": draft_id}, {}))

        gc = MagicMock()
        with patch("skills._m365.helpers.get_graph_client", return_value=gc):
            r = _approve(client, draft_id)
        assert r.status_code == 400, r.text

        drafts = _run(td.list_for_task("task-1"))
        assert drafts[0]["status"] == "pending", (
            "a retryable failure must release the durable status back to "
            "pending, not leave it stuck on 'sending'"
        )


class TestRestartRecoveryRehydration:
    def test_missing_in_memory_but_fresh_durable_row_is_rehydrated(self, td):
        """Simulates a backend restart: the draft never existed in this
        process's _pending_drafts at all, only in the durable table."""
        client = TestClient(app)
        draft_id = "durable-only-draft"
        _run(td.record_draft(
            "task-1", draft_id, "email-send",
            {"draft_id": draft_id},
            {"to": "bob@amd.com", "message": "hi"},
        ))
        assert _drafts.get_draft(draft_id) is None  # confirm "restart" state

        with patch("skills._m365.helpers.get_graph_client", return_value=_gc_for_send()):
            r = _approve(client, draft_id)
        assert r.status_code == 200, r.text

        drafts = _run(td.list_for_task("task-1"))
        assert drafts[0]["status"] == "sent"

    def test_expired_durable_row_is_not_rehydrated(self, td, monkeypatch):
        client = TestClient(app)
        draft_id = "expired-draft"
        _run(td.record_draft(
            "task-1", draft_id, "email-send",
            {"draft_id": draft_id},
            {"to": "bob@amd.com", "message": "hi"},
        ))
        # Backdate past the TTL.
        monkeypatch.setattr(td, "TASK_DRAFT_TTL_SECONDS", 60)
        import aiosqlite

        async def _backdate():
            async with aiosqlite.connect(td.DB_PATH) as db:
                old = (datetime.now(timezone.utc) - timedelta(seconds=120)).isoformat()
                await db.execute(
                    "UPDATE task_drafts SET created_at=? WHERE draft_id=?", (old, draft_id)
                )
                await db.commit()

        _run(_backdate())

        r = _approve(client, draft_id)
        assert r.status_code == 404, r.text
        assert _drafts.get_draft(draft_id) is None, (
            "an expired durable row must not be rehydrated into the live store"
        )

    def test_crashed_mid_send_durable_row_is_recovered_as_retryable(self, td):
        """Issue #54 review, round 1 (High finding #2): a durable row stuck
        in "sending" (the process crashed after claim_for_sending but before
        pop_draft/release) must not be permanently stranded — reaching
        _ensure_draft_loaded at all means there's no live in-memory
        claimant in *this* process, so it's safe to recover as retryable
        rather than showing an indefinite "check back in a moment" that
        never resolves."""
        client = TestClient(app)
        draft_id = "crashed-mid-send"
        _run(td.record_draft(
            "task-1", draft_id, "email-send",
            {"draft_id": draft_id}, {"to": "bob@amd.com", "message": "hi"},
        ))
        _run(td.sync_status(draft_id, "sending"))  # simulate the crash point
        assert _drafts.get_draft(draft_id) is None  # confirm "restart" state

        with patch("skills._m365.helpers.get_graph_client", return_value=_gc_for_send()):
            r = _approve(client, draft_id)
        assert r.status_code == 200, r.text

        drafts = _run(td.list_for_task("task-1"))
        assert drafts[0]["status"] == "sent"

    def test_already_sent_durable_row_is_not_rehydrated(self, td):
        """A draft already delivered (status='sent') must not be resurrected
        as claimable just because it's missing from memory."""
        client = TestClient(app)
        draft_id = "already-sent-draft"
        _run(td.record_draft(
            "task-1", draft_id, "email-send", {"draft_id": draft_id}, {"to": "a@b.com"}
        ))
        _run(td.sync_status(draft_id, "sent"))

        r = _approve(client, draft_id)
        assert r.status_code == 404, r.text


class TestConcurrentRehydrationDoesNotDoubleClaim:
    """Issue #54 review, round 1 (Critical finding #1): two concurrent
    requests for the same restart-recovered (durable-only) draft must not
    both succeed in claiming it — that would double-send. _ensure_draft_loaded
    must re-check the in-memory store immediately after its `await` on the
    durable-storage read, closing the TOCTOU window a naive
    check-then-await-then-write would leave open."""

    def test_only_one_concurrent_claim_succeeds(self, td, monkeypatch):
        import task_drafts as _td
        from routes.drafts import _ensure_draft_loaded
        from skills._drafts import claim_for_sending

        draft_id = "race-draft"
        _run(_td.record_draft(
            "task-1", draft_id, "email-send",
            {"draft_id": draft_id}, {"to": "a@b.com", "message": "hi"},
        ))

        release = asyncio.Event()
        real_get_for_rehydrate = _td.get_for_rehydrate

        async def _slow_get_for_rehydrate(did):
            # Force both concurrent callers to reach this suspension point
            # before either resumes and re-checks — this is exactly the
            # interleaving that reproduced the bug.
            await release.wait()
            return await real_get_for_rehydrate(did)

        monkeypatch.setattr(_td, "get_for_rehydrate", _slow_get_for_rehydrate)

        async def _attempt():
            await _ensure_draft_loaded(draft_id)
            return claim_for_sending(draft_id) is not None

        async def _run_race():
            t1 = asyncio.ensure_future(_attempt())
            t2 = asyncio.ensure_future(_attempt())
            await asyncio.sleep(0.05)  # let both reach `await release.wait()`
            release.set()
            return await asyncio.gather(t1, t2)

        results = _run(_run_race())
        assert sorted(results) == [False, True], (
            f"exactly one concurrent claim must succeed, got {results} "
            "(both True == double-claim == double-send)"
        )


class TestGetTaskReturnsDrafts:
    def test_get_task_status_includes_drafts_array(self, td, tmp_path, monkeypatch):
        import task_queue as tq

        monkeypatch.setattr(tq, "DB_PATH", td.DB_PATH)
        _run(tq.init_db())

        task_id = _run(tq.enqueue("do a thing"))
        _run(tq.get_task(task_id))  # sanity: task row exists
        _run(td.record_draft(
            task_id, "d1", "email-send", {"draft_id": "d1", "to": "a@b.com"}, {}
        ))

        client = TestClient(app)
        r = client.get(f"/api/tasks/{task_id}")
        assert r.status_code == 200, r.text
        body = r.json()
        assert "drafts" in body
        assert len(body["drafts"]) == 1
        assert body["drafts"][0]["draft_id"] == "d1"
        assert "params" not in body["drafts"][0], "must never leak the mutation payload to the frontend"
