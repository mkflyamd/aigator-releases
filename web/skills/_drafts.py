"""In-memory draft store for human-in-the-loop approval of outbound messages."""

import uuid
import time

_pending_drafts: dict[str, dict] = {}
_DRAFT_TTL_SECONDS = 1800  # 30 minutes

# Status values a draft may carry. "pending" (default) = awaiting user action;
# "sending" = approve endpoint has begun delivery (prevents double-send);
# "done" = delivery succeeded and the draft has been consumed.
# A draft left in "sending" by a crashed process is treated as retryable by
# approve_draft (see email.py) — the worst case is a double-send if the
# original send actually completed but the process died before flipping to
# "done", which is strictly better than the prior behavior (draft permanently
# lost on any transient error, retry returns 404).
_DRAFT_STATUS_PENDING = "pending"
_DRAFT_STATUS_SENDING = "sending"


def cleanup_drafts():
    now = time.time()
    expired = [
        k
        for k, v in _pending_drafts.items()
        if now - v["created_at"] > _DRAFT_TTL_SECONDS
    ]
    for k in expired:
        del _pending_drafts[k]


def create_draft(draft_type: str, params: dict, preview: dict) -> str:
    cleanup_drafts()
    draft_id = str(uuid.uuid4())
    _pending_drafts[draft_id] = {
        "id": draft_id,
        "type": draft_type,
        "params": params,
        "preview": preview,
        "created_at": time.time(),
        "status": _DRAFT_STATUS_PENDING,
    }
    return draft_id


def get_draft(draft_id: str) -> dict | None:
    """Return the draft WITHOUT removing it. Use mark_status to advance the
    draft through its lifecycle. Returns None if the draft is unknown or has
    expired."""
    cleanup_drafts()
    return _pending_drafts.get(draft_id)


def pop_draft(draft_id: str) -> dict | None:
    """Remove and return the draft. Callers should only call this AFTER
    delivery has succeeded — calling it before delivery permanently loses the
    draft on any transient upstream error (PR #10 review). Prefer
    get_draft + mark_status_sending + (deliver) + pop_draft on success."""
    cleanup_drafts()
    return _pending_drafts.pop(draft_id, None)


def mark_status(draft_id: str, status: str) -> bool:
    """Set the draft's status field. Returns True if the draft exists and was
    updated, False if the draft is unknown. Used by approve_draft to claim a
    draft as "sending" (preventing concurrent double-send) before delivery and
    to reset to "pending" on failure (so the user can retry)."""
    cleanup_drafts()
    draft = _pending_drafts.get(draft_id)
    if draft is None:
        return False
    draft["status"] = status
    return True


def claim_for_sending(draft_id: str) -> dict | None:
    """Atomically transition a draft from "pending" to "sending" and return
    it. Returns None if the draft is unknown OR already "sending" — this is
    the double-send guard (PR #10 review: a duplicate Approve click while the
    first request is still in flight must NOT re-deliver). On a failed
    delivery, the caller must call mark_status(draft_id, "pending") to release
    the claim so the user can retry; on success, pop_draft."""
    cleanup_drafts()
    draft = _pending_drafts.get(draft_id)
    if draft is None:
        return None
    if draft.get("status") == _DRAFT_STATUS_SENDING:
        return None
    draft["status"] = _DRAFT_STATUS_SENDING
    return draft
