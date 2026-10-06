"""Server-side store of sandbox access requests.

The model cannot approve its own request: a request changes state only via
decide(), which is reachable only from the CSRF-guarded routes in
routes/sandbox_routes.py. A run may use an approval only for the same tab and
exactly the same normalized set; an approval is used once and expires 10
minutes after the request was created. In-memory (single-process desktop
backend): a restart forgets pending requests, which only means asking again.
"""
from __future__ import annotations

import os
import threading
import time
import uuid
from dataclasses import dataclass

APPROVAL_TTL_SECONDS = 600


class ApprovalError(Exception):
    def __init__(self, status_code: int, detail: str):
        super().__init__(detail)
        self.status_code = status_code


@dataclass
class ApprovalRequest:
    id: str
    context_id: str
    read_paths: tuple[str, ...]
    write_paths: tuple[str, ...]
    network_hosts: tuple[str, ...]
    created_at: float
    status: str = "pending"  # pending | approved | denied


_LOCK = threading.Lock()
_REQUESTS: dict[str, ApprovalRequest] = {}


def _key(read_paths, write_paths, network_hosts) -> tuple:
    def paths(items):
        return tuple(sorted({os.path.normcase(str(p)) for p in items}))

    return paths(read_paths), paths(write_paths), tuple(sorted({h.lower() for h in network_hosts}))


def _expired(req: ApprovalRequest, now: float) -> bool:
    return now - req.created_at > APPROVAL_TTL_SECONDS


def _purge(now: float) -> None:
    for rid in [r.id for r in _REQUESTS.values() if now - r.created_at > 2 * APPROVAL_TTL_SECONDS]:
        del _REQUESTS[rid]


def create(context_id: str, read_paths, write_paths, network_hosts, now: float | None = None) -> ApprovalRequest:
    now = time.time() if now is None else now
    req = ApprovalRequest(
        id=uuid.uuid4().hex, context_id=context_id or "",
        read_paths=tuple(str(p) for p in read_paths), write_paths=tuple(str(p) for p in write_paths),
        network_hosts=tuple(network_hosts), created_at=now,
    )
    with _LOCK:
        _purge(now)
        _REQUESTS[req.id] = req
    return req


def lookup(context_id: str, read_paths, write_paths, network_hosts,
           now: float | None = None) -> tuple[str, ApprovalRequest | None]:
    """Newest request for this tab and exactly this set.

    approved -> consumed (removed); denied/expired -> reported once (removed);
    pending -> left in place; no match -> ("none", None).
    """
    now = time.time() if now is None else now
    key = _key(read_paths, write_paths, network_hosts)
    with _LOCK:
        matches = [
            r for r in _REQUESTS.values()
            if r.context_id == (context_id or "") and _key(r.read_paths, r.write_paths, r.network_hosts) == key
        ]
        if not matches:
            return "none", None
        req = max(matches, key=lambda r: r.created_at)
        if _expired(req, now):
            del _REQUESTS[req.id]
            return "expired", req
        if req.status == "pending":
            return "pending", req
        del _REQUESTS[req.id]
        return req.status, req


def decide(request_id: str, context_id: str, approve: bool, now: float | None = None) -> ApprovalRequest:
    now = time.time() if now is None else now
    with _LOCK:
        req = _REQUESTS.get(request_id)
        if req is None:
            raise ApprovalError(404, "This access request was not found or was already used. Ask AI Gator to run the code again.")
        if req.context_id != (context_id or ""):
            raise ApprovalError(409, "This access request belongs to a different tab.")
        if _expired(req, now):
            raise ApprovalError(410, "This access request expired (requests last 10 minutes). Ask AI Gator to run the code again.")
        if req.status != "pending":
            raise ApprovalError(409, f"This access request was already {req.status}.")
        req.status = "approved" if approve else "denied"
        return req


def _reset() -> None:
    with _LOCK:
        _REQUESTS.clear()
