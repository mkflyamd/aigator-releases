"""Which OS processes currently hold a coding-agent session open.

Gator only knows about the terminals it spawned itself. A probe asks the agent's own
on-disk registry about every process on this machine, so a session resumed from another
window is seen too. Each live process is a dict:

    {"pid": int, "session_id": str, "name": str | None, "started_at": float, "source": str}

To support another agent, write ``def probe(session_id=None) -> list[dict]`` and add it
to ``PROBES``. Nothing else needs to change.
"""

from __future__ import annotations

import json
import logging
import sys
from pathlib import Path
from typing import Callable

import psutil

logger = logging.getLogger(__name__)

_FILETIME_UNIX_EPOCH = 11644473600
_START_TOLERANCE_S = 2.0

Probe = Callable[..., list]


def _filetime_to_epoch(filetime: int) -> float:
    return filetime / 1e7 - _FILETIME_UNIX_EPOCH


def _same_process(entry: dict) -> bool:
    """True if the pid is alive and is the process that wrote the entry, not a reused pid."""
    try:
        created = psutil.Process(int(entry["pid"])).create_time()
    except (psutil.Error, KeyError, TypeError, ValueError):
        return False
    proc_start = entry.get("procStart")
    if proc_start is not None:
        try:
            return abs(created - _filetime_to_epoch(int(proc_start))) <= _START_TOLERANCE_S
        except (TypeError, ValueError):
            return False
    started_ms = entry.get("startedAt")
    if isinstance(started_ms, (int, float)):
        return created <= started_ms / 1000 + _START_TOLERANCE_S
    return False


def _claude_probe(session_id: str | None = None) -> list[dict]:
    root = Path.home() / ".claude" / "sessions"
    try:
        files = sorted(root.glob("*.json"))
    except OSError:
        return []
    found = []
    for path in files:
        try:
            entry = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        if not isinstance(entry, dict) or not entry.get("sessionId") or "pid" not in entry:
            continue
        if session_id is not None and entry["sessionId"] != session_id:
            continue
        domain = entry.get("pidDomain")
        if sys.platform == "win32" and isinstance(domain, str) and not domain.startswith("win32:"):
            continue
        if not _same_process(entry):
            continue
        started = entry.get("startedAt")
        found.append({
            "pid": int(entry["pid"]),
            "session_id": entry["sessionId"],
            "name": entry.get("name") or None,
            "started_at": started / 1000 if isinstance(started, (int, float)) else 0.0,
            "source": "claude-registry",
        })
    return found


def _no_registry(session_id: str | None = None) -> list[dict]:
    return []


PROBES: dict[str, Probe] = {
    "claude": _claude_probe,
    "codex": _no_registry,
    "crush": _no_registry,
}


def live_processes(agent: str, session_id: str | None = None) -> list[dict]:
    probe = PROBES.get(agent)
    if probe is None:
        return []
    try:
        return probe(session_id)
    except Exception:
        logger.exception("live-session probe failed for %s", agent)
        return []
