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


def test_release_claim_for_retry_releases_a_sending_claim():
    draft_id = _drafts.create_draft("slack-post", {"message": "hi"}, {})
    _drafts.claim_for_sending(draft_id)
    released = _drafts.release_claim_for_retry(draft_id)
    assert released is True
    assert _drafts._pending_drafts[draft_id]["status"] == "pending"


def test_release_claim_for_retry_returns_false_for_unknown_draft():
    assert _drafts.release_claim_for_retry("nonexistent") is False


def test_release_claim_for_retry_does_not_clobber_handed_off():
    """Regression (PR #58 review follow-up): if open_draft_in_outlook races
    in and marks a draft "handed_off" while an approve_draft delivery attempt
    is still in flight (already holding the "sending" claim from before the
    handoff), that delivery's later failure must NOT reset the draft back to
    "pending" — doing so would let a subsequent Approve retry send via Gator
    even though the user already has an independent native draft, exactly the
    duplicate-send bug the "handed_off" status exists to prevent."""
    draft_id = _drafts.create_draft("email-send", {"to": "a@b.com"}, {})
    _drafts.claim_for_sending(draft_id)  # approve_draft claims "sending"
    _drafts.mark_status(draft_id, "handed_off")  # races in and wins
    released = _drafts.release_claim_for_retry(draft_id)
    assert released is False, (
        "must refuse to release a claim that is no longer 'sending'"
    )
    assert _drafts._pending_drafts[draft_id]["status"] == "handed_off"
    # And the draft must remain permanently unclaimable via the normal path.
    assert _drafts.claim_for_sending(draft_id) is None


# ---------------------------------------------------------------------------
# claim_for_handoff / abort_handoff / complete_handoff (PR #58 review, round 2)
# ---------------------------------------------------------------------------
# These mirror claim_for_sending / release_claim_for_retry exactly, on the
# handoff side, so that whichever operation (Gator send vs. Outlook handoff)
# reserves the draft first excludes the other BEFORE either performs its
# external Graph side effect.


def test_claim_for_handoff_returns_draft_and_marks_handing_off():
    draft_id = _drafts.create_draft("email-send", {"to": "a@b.com"}, {})
    draft = _drafts.claim_for_handoff(draft_id)
    assert draft is not None
    assert draft["type"] == "email-send"
    assert _drafts._pending_drafts[draft_id]["status"] == "handing_off"


def test_claim_for_handoff_rejects_concurrent_handoff_claim():
    """A second Open-in-Outlook click while the first Graph call is still in
    flight must return None — a second native draft must never be created."""
    draft_id = _drafts.create_draft("email-send", {"to": "a@b.com"}, {})
    first = _drafts.claim_for_handoff(draft_id)
    second = _drafts.claim_for_handoff(draft_id)
    assert first is not None
    assert second is None


def test_claim_for_handoff_rejects_a_draft_already_sending():
    """Approve must exclude a concurrent handoff, and vice versa — whichever
    claims first wins."""
    draft_id = _drafts.create_draft("email-send", {"to": "a@b.com"}, {})
    _drafts.claim_for_sending(draft_id)
    assert _drafts.claim_for_handoff(draft_id) is None


def test_claim_for_sending_rejects_a_draft_already_handing_off():
    """The symmetric direction: a handoff that has claimed the draft but not
    yet completed must exclude a concurrent Approve."""
    draft_id = _drafts.create_draft("email-send", {"to": "a@b.com"}, {})
    _drafts.claim_for_handoff(draft_id)
    assert _drafts.claim_for_sending(draft_id) is None


def test_claim_for_handoff_returns_none_for_unknown_draft():
    assert _drafts.claim_for_handoff("nonexistent") is None


def test_abort_handoff_releases_a_handing_off_claim():
    draft_id = _drafts.create_draft("email-send", {"to": "a@b.com"}, {})
    _drafts.claim_for_handoff(draft_id)
    released = _drafts.abort_handoff(draft_id)
    assert released is True
    assert _drafts._pending_drafts[draft_id]["status"] == "pending"
    # A retry (e.g. a second Open-in-Outlook click after a failed Graph call)
    # must now succeed.
    assert _drafts.claim_for_handoff(draft_id) is not None


def test_abort_handoff_is_a_noop_for_other_statuses():
    draft_id = _drafts.create_draft("email-send", {"to": "a@b.com"}, {})
    _drafts.claim_for_sending(draft_id)
    assert _drafts.abort_handoff(draft_id) is False
    assert _drafts._pending_drafts[draft_id]["status"] == "sending"


def test_abort_handoff_returns_false_for_unknown_draft():
    assert _drafts.abort_handoff("nonexistent") is False


def test_complete_handoff_finalizes_as_handed_off():
    draft_id = _drafts.create_draft("email-send", {"to": "a@b.com"}, {})
    _drafts.claim_for_handoff(draft_id)
    completed = _drafts.complete_handoff(draft_id)
    assert completed is True
    assert _drafts._pending_drafts[draft_id]["status"] == "handed_off"
    # Terminal: neither claim path may ever reclaim it again.
    assert _drafts.claim_for_sending(draft_id) is None
    assert _drafts.claim_for_handoff(draft_id) is None


def test_complete_handoff_is_a_noop_for_other_statuses():
    draft_id = _drafts.create_draft("email-send", {"to": "a@b.com"}, {})
    assert _drafts.complete_handoff(draft_id) is False
    assert _drafts._pending_drafts[draft_id]["status"] == "pending"


def test_complete_handoff_returns_false_for_unknown_draft():
    assert _drafts.complete_handoff("nonexistent") is False
