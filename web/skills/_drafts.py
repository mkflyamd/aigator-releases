"""In-memory draft store for human-in-the-loop approval of outbound messages."""

import uuid
import time

_pending_drafts: dict[str, dict] = {}
_DRAFT_TTL_SECONDS = 1800  # 30 minutes


def cleanup_drafts():
    now = time.time()
    expired = [k for k, v in _pending_drafts.items() if now - v["created_at"] > _DRAFT_TTL_SECONDS]
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
    }
    return draft_id


def pop_draft(draft_id: str) -> dict | None:
    cleanup_drafts()
    return _pending_drafts.pop(draft_id, None)
