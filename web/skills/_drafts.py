"""In-memory draft store for human-in-the-loop approval of outbound messages."""

import uuid
import time

_pending_drafts: dict[str, dict] = {}
_DRAFT_TTL_SECONDS = 1800  # 30 minutes

# Status values a draft may carry. "pending" (default) = awaiting user action;
# unclaimable statuses below all mean "some operation already owns this
# draft's one shot at an external side effect."
#
# "sending" = approve endpoint has begun delivery (prevents double-send).
# A draft left in "sending" by a crashed process is treated as retryable by
# approve_draft (see email.py) — the worst case is a double-send if the
# original send actually completed but the process died before flipping to
# "done", which is strictly better than the prior behavior (draft permanently
# lost on any transient error, retry returns 404).
#
# "handing_off" / "handed_off" = a parallel native draft (e.g. an OWA draft
# created by open_draft_in_outlook) is being created / has been created and
# now owns delivery for this content.
#
# PR #58 review, round 2: the first fix only stopped a *failed* approve from
# clobbering a "handed_off" status back to "pending". It missed the deeper
# race — open_draft_in_outlook used to create the OWA draft via Graph FIRST
# and only mark "handed_off" afterward, so a concurrent Approve could claim
# "sending" and deliver via Gator in the gap before that mark landed, giving
# both a sent Gator message and an independently sendable OWA draft. The fix
# is symmetric mutual exclusion: claim_for_handoff reserves "handing_off"
# (exactly like claim_for_sending reserves "sending") BEFORE any Graph call,
# so whichever operation (send or handoff) claims the draft first locks the
# other out before either performs its external side effect — not after.
#
# All read-check-write transitions below are synchronous with no `await` in
# between, so they're atomic with respect to the single-process asyncio event
# loop this app runs on (Python only switches coroutines at an `await`) —
# this is a single-worker desktop backend, not a multi-process/multi-worker
# service, so no additional lock is needed for that model to hold.
_DRAFT_STATUS_PENDING = "pending"
_DRAFT_STATUS_SENDING = "sending"
_DRAFT_STATUS_HANDING_OFF = "handing_off"
_DRAFT_STATUS_HANDED_OFF = "handed_off"
_DRAFT_STATUS_CLAIMED = (
    _DRAFT_STATUS_SENDING,
    _DRAFT_STATUS_HANDING_OFF,
    _DRAFT_STATUS_HANDED_OFF,
)


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
    """Set the draft's status field unconditionally, bypassing all the
    mutual-exclusion guards below. This is a low-level primitive kept for
    direct test setup — production code should use the guarded
    claim_for_sending / release_claim_for_retry / claim_for_handoff /
    abort_handoff / complete_handoff functions instead, which enforce that a
    draft can only be claimed once and only released by the operation that
    holds its claim."""
    cleanup_drafts()
    draft = _pending_drafts.get(draft_id)
    if draft is None:
        return False
    draft["status"] = status
    return True


def claim_for_sending(draft_id: str) -> dict | None:
    """Atomically transition a draft from "pending" to "sending" and return
    it. Returns None if the draft is unknown or already claimed — by another
    in-flight send (PR #10 review: a duplicate Approve click while the first
    request is still in flight must NOT re-deliver), or by a Outlook handoff
    in progress or completed (PR #58 review: an operation that will create
    or has created an independent native draft must exclude Gator delivery,
    and vice versa — see claim_for_handoff). On a failed delivery, the caller
    must call release_claim_for_retry(draft_id) to release the claim so the
    user can retry; on success, pop_draft."""
    cleanup_drafts()
    draft = _pending_drafts.get(draft_id)
    if draft is None:
        return None
    if draft.get("status") in _DRAFT_STATUS_CLAIMED:
        return None
    draft["status"] = _DRAFT_STATUS_SENDING
    return draft


def release_claim_for_retry(draft_id: str) -> bool:
    """Release a "sending" claim back to "pending" after a failed delivery,
    so the user can retry. A no-op (returns False) if the draft is not
    currently "sending" — in particular, this must never be able to reset a
    "handing_off"/"handed_off" draft back to "pending", since nothing besides
    this exact operation's own claim should ever release it."""
    cleanup_drafts()
    draft = _pending_drafts.get(draft_id)
    if draft is None:
        return False
    if draft.get("status") != _DRAFT_STATUS_SENDING:
        return False
    draft["status"] = _DRAFT_STATUS_PENDING
    return True


def claim_for_handoff(draft_id: str) -> dict | None:
    """Atomically transition a draft from "pending" to "handing_off" and
    return it — the handoff-side mirror of claim_for_sending. Must be called
    BEFORE any Graph call that creates the native draft, not after: claiming
    first is what makes the two operations mutually exclusive. Returns None
    if the draft is unknown or already claimed (an in-flight send, a handoff
    already in progress, or a completed handoff — a second Open-in-Outlook
    click must not create a second native draft). On failure to create the
    native draft, the caller must call abort_handoff(draft_id); on success,
    complete_handoff(draft_id)."""
    cleanup_drafts()
    draft = _pending_drafts.get(draft_id)
    if draft is None:
        return None
    if draft.get("status") in _DRAFT_STATUS_CLAIMED:
        return None
    draft["status"] = _DRAFT_STATUS_HANDING_OFF
    return draft


def abort_handoff(draft_id: str) -> bool:
    """Release a "handing_off" claim back to "pending" after the native
    draft could not be created, so the user can retry. A no-op (returns
    False) if the draft is not currently "handing_off"."""
    cleanup_drafts()
    draft = _pending_drafts.get(draft_id)
    if draft is None:
        return False
    if draft.get("status") != _DRAFT_STATUS_HANDING_OFF:
        return False
    draft["status"] = _DRAFT_STATUS_PENDING
    return True


def complete_handoff(draft_id: str) -> bool:
    """Finalize a successful handoff: "handing_off" -> "handed_off"
    (terminal — claim_for_sending and claim_for_handoff both refuse it
    forever after). A no-op (returns False) if the draft is not currently
    "handing_off"."""
    cleanup_drafts()
    draft = _pending_drafts.get(draft_id)
    if draft is None:
        return False
    if draft.get("status") != _DRAFT_STATUS_HANDING_OFF:
        return False
    draft["status"] = _DRAFT_STATUS_HANDED_OFF
    return True
