"""Per-tab approvals that last for the whole chat tab.

Created only by the CSRF-guarded approve route in routes/sandbox_routes.py.
There is no time limit. They end when the tab is closed (routes/conversation_routes.py)
or when the backend restarts: in-memory, so a restart only means asking again.
"""
from __future__ import annotations

import threading
from dataclasses import dataclass

from .paths import paths_covered


@dataclass(frozen=True)
class _Grant:
    context_id: str
    read: tuple[str, ...]
    write: tuple[str, ...]
    hosts: tuple[str, ...]


_LOCK = threading.Lock()
_GRANTS: list[_Grant] = []


def add(context_id: str, read, write, hosts) -> None:
    grant = _Grant(context_id or "", tuple(str(p) for p in read), tuple(str(p) for p in write),
                   tuple(h.lower() for h in hosts))
    with _LOCK:
        _GRANTS.append(grant)


def covers(context_id: str, read, write, hosts) -> bool:
    with _LOCK:
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
