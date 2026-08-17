"""Tests for the PR #10 review fix: drafts must survive a transient delivery
failure so the user can retry. Previously pop_draft ran BEFORE the delivery
attempt, so any Graph/Slack/Teams error permanently consumed the draft
(retry → 404). Now claim_for_sending transitions the draft to "sending"
(preventing double-send), and the draft is only pop'd on confirmed success.
"""

import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).parent.parent / "web"))

from skills import _drafts


def setup_function(function):
    _drafts._pending_drafts.clear()


def test_claim_for_sending_returns_draft_and_marks_sending():
    draft_id = _drafts.create_draft("slack-post", {"message": "hi"}, {})
    draft = _drafts.claim_for_sending(draft_id)
    assert draft is not None
    assert draft["type"] == "slack-post"
    assert _drafts._pending_drafts[draft_id]["status"] == "sending"


def test_claim_for_sending_rejects_concurrent_claim():
    """A second claim while the first is in-flight must return None — this is
    the double-send guard (duplicate Approve click)."""
    draft_id = _drafts.create_draft("slack-post", {"message": "hi"}, {})
    first = _drafts.claim_for_sending(draft_id)
    second = _drafts.claim_for_sending(draft_id)
    assert first is not None
    assert second is None


def test_mark_status_pending_releases_claim_for_retry():
    """On delivery failure, mark_status(draft_id, 'pending') must release the
    claim so the user can retry."""
    draft_id = _drafts.create_draft("slack-post", {"message": "hi"}, {})
    _drafts.claim_for_sending(draft_id)
    assert _drafts._pending_drafts[draft_id]["status"] == "sending"
    released = _drafts.mark_status(draft_id, "pending")
    assert released is True
    assert _drafts._pending_drafts[draft_id]["status"] == "pending"
    # A new claim must now succeed (retry path).
    retry = _drafts.claim_for_sending(draft_id)
    assert retry is not None


def test_pop_draft_removes_on_success():
    """On confirmed delivery success, pop_draft must remove the draft."""
    draft_id = _drafts.create_draft("slack-post", {"message": "hi"}, {})
    _drafts.claim_for_sending(draft_id)
    removed = _drafts.pop_draft(draft_id)
    assert removed is not None
    assert draft_id not in _drafts._pending_drafts


def test_claim_returns_none_for_unknown_draft():
    assert _drafts.claim_for_sending("nonexistent") is None


def test_get_draft_does_not_remove():
    """get_draft must return the draft without removing it (for inspecting
    status without consuming the draft)."""
    draft_id = _drafts.create_draft("slack-post", {"message": "hi"}, {})
    draft = _drafts.get_draft(draft_id)
    assert draft is not None
    assert draft_id in _drafts._pending_drafts
    # get_draft again still works (not consumed).
    draft2 = _drafts.get_draft(draft_id)
    assert draft2 is not None


def test_failed_delivery_then_retry_succeeds_end_to_end():
    """Simulate the full PR #10 scenario: delivery fails, claim is released,
    user retries, delivery succeeds, draft is consumed."""
    draft_id = _drafts.create_draft("slack-post", {"message": "hi"}, {})

    # Attempt 1: delivery fails (simulated).
    draft1 = _drafts.claim_for_sending(draft_id)
    assert draft1 is not None
    _drafts.mark_status(draft_id, "pending")  # release on failure
    assert _drafts._pending_drafts[draft_id]["status"] == "pending"

    # Attempt 2 (retry): delivery succeeds.
    draft2 = _drafts.claim_for_sending(draft_id)
    assert draft2 is not None
    _drafts.pop_draft(draft_id)
    assert draft_id not in _drafts._pending_drafts
