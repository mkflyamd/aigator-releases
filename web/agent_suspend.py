"""Suspend idle agent terminals to give their memory back.

A live `claude --resume` terminal costs 550-970 MB. An agent that has finished
its turn, that nobody is looking at, is only holding that memory. This kills its
process and leaves a record (which stored session it was) so the tab can bring
it back with the agent's own resume command.

Only terminals whose state the agent itself reports (see agent_state) and whose
stored session is known are touched: a working or asking agent, an agent with no
hooks, and the plain terminal are never suspended.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import threading
import time
from pathlib import Path

import agent_state
import generic_agent

logger = logging.getLogger(__name__)

IDLE_SUSPEND_SECONDS = 1800
MAX_LIVE_AGENT_TERMINALS = 4
SWEEP_INTERVAL = 60.0
VIEWED_GRACE_SECONDS = 90.0
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
    rest = [pty for _at, pty in suspendable if pty not in timed_out]
    return timed_out + rest[: max(excess, 0)]


def _load() -> dict[str, dict]:
    try:
        data = json.loads(STATE_FILE.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def _save(records: dict[str, dict]) -> None:
    STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    tmp = STATE_FILE.with_name(STATE_FILE.name + ".tmp")
    tmp.write_text(json.dumps(records), encoding="utf-8")
    os.replace(tmp, STATE_FILE)


def suspended_record(pty_id: str) -> dict | None:
    with _file_lock:
        record = _load().get(pty_id)
    return record if isinstance(record, dict) else None


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


def _suspend(pty_id: str, meta: dict, now: float) -> bool:
    from routes import terminal

    agent, project_id = meta["agent"], meta.get("project_id")
    _remember(pty_id, {"agent": agent, "project_id": project_id, "session_id": meta["session_id"], "at": now}, now)
    try:
        terminal.close_pty_session(pty_id)
    except Exception:
        logger.warning("could not suspend terminal %s", pty_id, exc_info=True)
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
        # Looked at between the check above and now: leave it running.
        if terminal.has_viewer(pty, VIEWED_GRACE_SECONDS):
            continue
        if _suspend(pty, live[pty], now):
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
