"""Per-tab approvals that last for one task.

Created only by the CSRF-guarded approve route in routes/sandbox_routes.py.
Ended when the user sends the next message in the tab (routes/chat.py) or after
TASK_TTL_SECONDS. In-memory: a restart forgets them, which only means asking again.
"""
from __future__ import annotations

import threading
import time
from dataclasses import dataclass

from .paths import paths_covered

TASK_TTL_SECONDS = 600


@dataclass(frozen=True)
class _Grant:
    context_id: str
    read: tuple[str, ...]
    write: tuple[str, ...]
    hosts: tuple[str, ...]
    expires: float


_LOCK = threading.Lock()
_GRANTS: list[_Grant] = []


def _purge(now: float) -> None:
    _GRANTS[:] = [g for g in _GRANTS if g.expires >= now]


def add(context_id: str, read, write, hosts, now: float | None = None) -> None:
    now = time.time() if now is None else now
    grant = _Grant(context_id or "", tuple(str(p) for p in read), tuple(str(p) for p in write),
                   tuple(h.lower() for h in hosts), now + TASK_TTL_SECONDS)
    with _LOCK:
        _purge(now)
        _GRANTS.append(grant)


def covers(context_id: str, read, write, hosts, now: float | None = None) -> bool:
    now = time.time() if now is None else now
    with _LOCK:
        _purge(now)
        live = [g for g in _GRANTS if g.context_id == (context_id or "")]
    granted_read = [p for g in live for p in g.read]
    granted_write = [p for g in live for p in g.write]
    granted_hosts = {h for g in live for h in g.hosts}
    return paths_covered(read, write, granted_read, granted_write) and {h.lower() for h in hosts} <= granted_hosts


def end_for_tab(context_id: str) -> None:
    with _LOCK:
        _GRANTS[:] = [g for g in _GRANTS if g.context_id != (context_id or "")]


def _reset() -> None:
    with _LOCK:
        _GRANTS.clear()
