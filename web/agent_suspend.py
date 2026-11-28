"""Suspend idle agent terminals to give their memory back.

A live `claude --resume` terminal costs 550-970 MB. An agent that has finished
its turn, that nobody is looking at, is only holding that memory. This kills its
process and leaves a record (which stored session it was) so the tab can bring
it back with the agent's own resume command.

Only terminals whose state the agent itself reports (see agent_state) and whose
stored session is known are touched: a working or asking agent, an agent with no
hooks, and the plain terminal are never suspended. A remote-control terminal is
suspended like any other: its lane keeps the record, and the next chat message
wakes it (see remote/service.py).
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import threading
import time
from datetime import datetime, timezone
from pathlib import Path

import agent_state
import generic_agent

logger = logging.getLogger(__name__)

IDLE_SUSPEND_SECONDS = 1800
MAX_LIVE_AGENT_TERMINALS = 4
SWEEP_INTERVAL = 60.0
VIEWED_GRACE_SECONDS = 90.0
# Over the terminal cap, only a terminal idle at least this long may go: a turn that
# just finished is likely to be followed by another.
CAP_MIN_IDLE_SECONDS = 300
# The idle state is stamped by the Stop hook, which lands under a second after the
# last transcript write, so the transcript may predate it by about that much.
TRANSCRIPT_SLACK_SECONDS = 2.0
RECORD_RETENTION_SECONDS = 14 * 86400

STATE_FILE = Path.home() / ".gator" / "suspended-agents.json"
_file_lock = threading.Lock()
# pty id -> when the sweep first saw it unwatched. Cleared whenever it is watched.
_unwatched_since: dict[str, float] = {}


def _counts_as_agent(meta: dict) -> bool:
    agent = meta.get("agent")
    return bool(agent) and agent != generic_agent.TERMINAL_AGENT


def choose(
    live: dict[str, dict],
    states: dict[str, dict],
    watched: set[str],
    unwatched_since: dict[str, float],
    now: float,
) -> list[str]:
    """Terminals to suspend, oldest idle first: those idle and unwatched for
    IDLE_SUSPEND_SECONDS, then as many more of the least recently active idle ones
    as it takes to get back to MAX_LIVE_AGENT_TERMINALS."""
    suspendable = []
    for pty, meta in live.items():
        state = states.get(pty)
        if not _counts_as_agent(meta) or not meta.get("session_id"):
            continue
        if not state or state["state"] != "idle" or pty in watched:
            continue
        suspendable.append((state["at"], pty))
    suspendable.sort()
    timed_out = [
        pty
        for at, pty in suspendable
        if now - at >= IDLE_SUSPEND_SECONDS and now - unwatched_since.get(pty, now) >= IDLE_SUSPEND_SECONDS
    ]
    excess = sum(1 for meta in live.values() if _counts_as_agent(meta)) - len(timed_out) - MAX_LIVE_AGENT_TERMINALS
    rest = [pty for at, pty in suspendable if pty not in timed_out and now - at >= CAP_MIN_IDLE_SECONDS]
    return timed_out + rest[: max(excess, 0)]


def _load() -> dict[str, dict]:
    try:
        data = json.loads(STATE_FILE.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def _write_atomic(path: Path, body: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f"{path.name}.{os.getpid()}.tmp")
    tmp.write_text(body, encoding="utf-8")
    os.replace(tmp, path)


def targets_file() -> Path:
    return STATE_FILE.parent / "wake" / "targets.json"


def _write_targets(records: dict[str, dict]) -> None:
    """The suspended agents another agent can ask Gator to wake, for agents that
    do not find a peer in ListAgents."""
    targets = [
        {
            "name": r.get("title") or r["session_id"],
            "session_id": r["session_id"],
            "agent": r["agent"],
            "project_id": r.get("project_id"),
            "suspended_since": datetime.fromtimestamp(r["at"], timezone.utc).isoformat(timespec="seconds"),
        }
        for r in records.values()
        if r.get("agent") == "claude" and r.get("session_id") and not r.get("failed")
    ]
    _write_atomic(targets_file(), json.dumps(targets, indent=2))


def _save(records: dict[str, dict]) -> None:
    _write_atomic(STATE_FILE, json.dumps(records))
    try:
        _write_targets(records)
    except (OSError, KeyError, TypeError, ValueError):
        logger.warning("could not write the wake targets file", exc_info=True)


def suspended_record(pty_id: str) -> dict | None:
    with _file_lock:
        record = _load().get(pty_id)
    return record if isinstance(record, dict) else None


def all_records() -> dict[str, dict]:
    with _file_lock:
        return {k: v for k, v in _load().items() if isinstance(v, dict)}


def mark_failed(pty_id: str, failure: dict) -> None:
    """Keep a record whose wake failed, with why and the message that was not delivered."""
    with _file_lock:
        records = _load()
        record = records.get(pty_id)
        if isinstance(record, dict):
            records[pty_id] = {**record, "failed": failure}
            _save(records)


def clear_failed(pty_id: str) -> None:
    with _file_lock:
        records = _load()
        record = records.get(pty_id)
        if isinstance(record, dict) and "failed" in record:
            records[pty_id] = {k: v for k, v in record.items() if k != "failed"}
            _save(records)


def forget(pty_id: str) -> None:
    with _file_lock:
        records = _load()
        if records.pop(pty_id, None) is not None:
            _save(records)


def _remember(pty_id: str, record: dict, now: float) -> None:
    with _file_lock:
        records = {
            k: v
            for k, v in _load().items()
            if isinstance(v, dict) and now - v.get("at", 0) < RECORD_RETENTION_SECONDS
        }
        records[pty_id] = record
        _save(records)


def _current_session(meta: dict, idle_at: float) -> dict | None:
    """The stored session the tab would resume, when it is on disk and has not gone
    stale (an agent that continues under a new session id leaves the old one behind)."""
    from agent_sessions import find_session
    from skills.code_agent.projects import get_project

    repo_path = (get_project(meta.get("project_id") or "") or {}).get("repo_path")
    if not repo_path:
        logger.debug("not suspending %s: no project %r", meta.get("session_id"), meta.get("project_id"))
        return None
    try:
        rec = find_session(repo_path, meta["agent"], meta["session_id"])
    except Exception:
        logger.warning("could not look up the stored session for %s", meta.get("session_id"), exc_info=True)
        return None
    current = rec is not None and rec["last_active_at"] >= idle_at - TRANSCRIPT_SLACK_SECONDS
    if not current:
        logger.debug(
            "not suspending %s: stored session %s",
            meta["session_id"],
            "not found" if rec is None else "older than the idle state",
        )
    return rec if current else None


def _suspend(pty_id: str, meta: dict, idle_at: float, now: float) -> bool:
    import agent_wake

    if not agent_wake.claim(meta["session_id"]):
        return False
    try:
        return _suspend_claimed(pty_id, meta, idle_at, now)
    finally:
        agent_wake.release(meta["session_id"])


def _suspend_claimed(pty_id: str, meta: dict, idle_at: float, now: float) -> bool:
    from routes import terminal

    stored = _current_session(meta, idle_at)
    if not stored:
        return False
    # Last look before the kill: it was viewed, or the agent moved on, while the
    # lookup above ran.
    if terminal.has_viewer(pty_id, VIEWED_GRACE_SECONDS):
        return False
    state = agent_state.read_states([pty_id]).get(pty_id)
    if not state or state["state"] != "idle" or state["at"] != idle_at:
        return False
    agent, project_id = meta["agent"], meta.get("project_id")
    record = {
        "agent": agent,
        "project_id": project_id,
        "session_id": meta["session_id"],
        "title": stored.get("title") or "",
        "at": now,
    }
    _remember(pty_id, record, now)
    if not terminal.close_pty_session(pty_id):
        logger.warning("could not suspend terminal %s", pty_id)
        forget(pty_id)
        return False
    generic_agent.unpin_session(pty_id)
    if project_id and generic_agent.get_active_session(project_id, agent) == pty_id:
        generic_agent.clear_active_session(project_id, agent)
    return True


def sweep(now: float | None = None) -> list[str]:
    """One pass. Blocking (reads state files, talks to the PTY host). Returns the
    ids it suspended."""
    from routes import terminal

    now = time.time() if now is None else now
    live = terminal.live_pty_labels()
    states = agent_state.read_states(list(live))
    watched = {pty for pty in live if terminal.has_viewer(pty, VIEWED_GRACE_SECONDS)}
    for pty in list(_unwatched_since):
        if pty not in live or pty in watched:
            del _unwatched_since[pty]
    for pty in live:
        if pty not in watched:
            _unwatched_since.setdefault(pty, now)
    suspended = []
    for pty in choose(live, states, watched, _unwatched_since, now):
        if _suspend(pty, live[pty], states[pty]["at"], now):
            suspended.append(pty)
            _unwatched_since.pop(pty, None)
    return suspended


async def run() -> None:
    while True:
        await asyncio.sleep(SWEEP_INTERVAL)
        try:
            done = await asyncio.to_thread(sweep)
            if done:
                logger.info("suspended %d idle agent terminal(s)", len(done))
        except Exception:
            logger.warning("idle terminal sweep failed", exc_info=True)
