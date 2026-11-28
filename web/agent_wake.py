"""Let one agent wake a suspended agent session and hand it one message.

A suspended agent has no process, so a message sent to it has nowhere to land. This
resumes that same stored session in its own tab, waits until the agent reports it is
ready, types the message in as one paste, and leaves the normal idle rules to suspend
it again.

Who is asking comes from the caller (the front door knows which agent it is talking
to), never from the message text. Only existing sessions are resumed: nothing here
starts a new session or runs a command.
"""

from __future__ import annotations

import asyncio
import json
import logging
import re
import threading
import time
from collections import deque
from collections.abc import Awaitable, Callable
from datetime import datetime, timezone
from pathlib import Path

import agent_sessions
import agent_state
import agent_suspend
from relay import settings as relay_settings

logger = logging.getLogger(__name__)

MESSAGE_MAX_BYTES = 4096
NAME_MAX_CHARS = 60
PREVIEW_CHARS = 200
SENDER_LIMIT = 5
SENDER_WINDOW_SECONDS = 3600.0
WAKE_READY_SECONDS = 90.0
LIVE_READY_SECONDS = 300.0
USER_TYPING_SECONDS = 20.0
READY_POLL_SECONDS = 0.5
PASTE_TO_ENTER_SECONDS = 0.4
AUDIT_KEEP = 200
UNAUTHORIZED_AUDIT_SECONDS = 60.0

BRACKETED_PASTE_ON = "\x1b[?2004h"

_ESCAPES = re.compile(r"\x1b\[[0-?]*[ -/]*[@-~]|\x1b\][^\x07\x1b]*(?:\x07|\x1b\\)|\x1b[@-_]")
_CONTROL = re.compile("[\x00-\x1f\x7f-\x9f\u200b-\u200f\u202a-\u202e\u2066-\u2069\ufeff]")

_lock = threading.Lock()
_audit_lock = threading.Lock()
_in_flight: set[str] = set()
_sent: dict[str, deque] = {}
_last_unauthorized = float("-inf")


class WakeRefused(Exception):
    """The wake or the delivery did not happen. `code` is for the caller, `reason` is for people."""

    def __init__(self, code: str, reason: str, **extra):
        super().__init__(reason)
        self.code = code
        self.reason = reason
        self.extra = extra

    def as_result(self) -> dict:
        return {"status": self.code, "reason": self.reason, **self.extra}


def audit_file() -> Path:
    return agent_suspend.STATE_FILE.parent / "wake" / "audit.jsonl"


def clean(text: str) -> str:
    """One line of plain text: no escape sequences, control characters or line breaks."""
    text = _ESCAPES.sub("", str(text))
    return " ".join(_CONTROL.sub(" ", text).split())


USER_TAG = "[via remote chat from the user]"


def frame(sender_name: str, message: str, origin: str = "agent") -> str:
    """The text that is typed into the target. It always starts with the tag, so it can
    never begin with a command character. `origin="user"` is a person typing in a chat app:
    it is their own words, not another agent's."""
    name = " ".join(clean(sender_name).replace("[", " ").replace("]", " ").split())[:NAME_MAX_CHARS] or "another agent"
    body = clean(message)
    if not body:
        raise WakeRefused("invalid", "The message is empty.")
    if len(body.encode("utf-8")) > MESSAGE_MAX_BYTES:
        raise WakeRefused("invalid", f"The message is longer than {MESSAGE_MAX_BYTES} bytes.")
    if origin == "user":
        return f"{USER_TAG} {body}"
    return f"[Message from {name} via AI Gator, from another agent, not from the user] {body}"


def claim(key: str) -> bool:
    """Take the one wake/suspend slot for a session. The idle sweep takes it too, so a
    terminal is never suspended in the middle of a delivery or woken in the middle of a suspend."""
    with _lock:
        if key in _in_flight:
            return False
        _in_flight.add(key)
        return True


def release(key: str) -> None:
    with _lock:
        _in_flight.discard(key)


def _spend_sender_slot(sender_key: str, now: float) -> None:
    with _lock:
        stamps = _sent.setdefault(sender_key, deque())
        while stamps and now - stamps[0] >= SENDER_WINDOW_SECONDS:
            stamps.popleft()
        if len(stamps) >= SENDER_LIMIT:
            raise WakeRefused(
                "rate_limited",
                f"At most {SENDER_LIMIT} wake messages an hour per agent; try again later.",
            )
        stamps.append(now)


def _audit(sender: dict, target: dict | None, outcome: str, text: str, now: float) -> None:
    _write_audit(
        {
            "at": _stamp(now),
            "sender": clean(sender.get("name", ""))[:NAME_MAX_CHARS],
            "target": (target or {}).get("title") or (target or {}).get("session_id") or "",
            "outcome": outcome,
            "message": text[:PREVIEW_CHARS],
        }
    )


def audit_refusal(sender: dict | None, target, code: str, reason: str, message, now: float | None = None) -> None:
    """One audit line for an attempt that delivered nothing. The message text is never
    kept, only its size: refused text may be sensitive. Blocking."""
    now = time.time() if now is None else now
    if code == "unauthorized" and not _unauthorized_due(now):
        return
    _write_audit(
        {
            "at": _stamp(now),
            "sender": clean((sender or {}).get("name", ""))[:NAME_MAX_CHARS],
            "target": clean(target)[:NAME_MAX_CHARS] if isinstance(target, str) else "",
            "outcome": code,
            "reason": reason,
            "message_bytes": len(message.encode("utf-8")) if isinstance(message, str) else 0,
        }
    )


def _stamp(now: float) -> str:
    return datetime.fromtimestamp(now, timezone.utc).isoformat(timespec="seconds")


def _unauthorized_due(now: float) -> bool:
    """Anything on this machine can knock without a token, so those lines are kept to one
    a minute: a flood must not push the real ones out of the trimmed file."""
    global _last_unauthorized
    with _lock:
        if now - _last_unauthorized < UNAUTHORIZED_AUDIT_SECONDS:
            return False
        _last_unauthorized = now
        return True


def _write_audit(line: dict) -> None:
    path = audit_file()
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with _audit_lock:
            lines = path.read_text(encoding="utf-8").splitlines() if path.exists() else []
            lines = [*lines[-(AUDIT_KEEP - 1) :], json.dumps(line)]
            path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    except OSError:
        logger.warning("could not write the wake audit line", exc_info=True)


def recent_audit(limit: int = 50) -> list[dict]:
    try:
        lines = audit_file().read_text(encoding="utf-8").splitlines()
    except OSError:
        return []
    out = []
    for raw in lines[-limit:]:
        try:
            out.append(json.loads(raw))
        except ValueError:
            continue
    return out


def _project_repo(project_id: str | None) -> str | None:
    from skills.code_agent.projects import get_project

    return (get_project(project_id or "") or {}).get("repo_path") or None


def title_of(project_id: str | None, agent: str, session_id: str) -> str:
    repo = _project_repo(project_id)
    if not repo:
        return ""
    try:
        rec = agent_sessions.find_session(repo, agent, session_id)
    except Exception:
        logger.warning("could not look up the session %s", session_id, exc_info=True)
        return ""
    return (rec or {}).get("title") or ""


def find_targets(target: str, project_id: str | None, allow_cross_project: bool = False) -> list[dict]:
    """The sessions the name or id matches: suspended ones from the records, running
    ones from the live terminals. Blocking."""
    from routes import terminal

    wanted = clean(target).casefold()
    if not wanted or (not project_id and not allow_cross_project):
        return []
    found: list[dict] = []
    seen: set[str] = set()

    def consider(entry: dict) -> None:
        if entry["agent"] != "claude" or not entry["session_id"] or entry["session_id"] in seen:
            return
        if not allow_cross_project and entry["project_id"] != project_id:
            return
        if wanted not in (entry["session_id"].casefold(), clean(entry["title"]).casefold()):
            return
        seen.add(entry["session_id"])
        found.append(entry)

    for pty_id, record in agent_suspend.all_records().items():
        consider(_suspended_entry(pty_id, record))
    for pty_id, meta in terminal.live_pty_labels().items():
        if meta.get("agent") != "claude" or not meta.get("session_id"):
            continue
        if not allow_cross_project and meta.get("project_id") != project_id:
            continue
        consider(_live_entry(pty_id, meta))
    return found


def _suspended_entry(pty_id: str, record: dict) -> dict:
    return {
        "state": "suspended",
        "pty_id": pty_id,
        "agent": record.get("agent", ""),
        "project_id": record.get("project_id"),
        "session_id": record.get("session_id", ""),
        "title": record.get("title") or "",
    }


def _live_entry(pty_id: str, meta: dict) -> dict:
    return {
        "state": "live",
        "pty_id": pty_id,
        "remote_pinned": meta.get("remote_pinned") == "1",
        "agent": "claude",
        "project_id": meta.get("project_id"),
        "session_id": meta["session_id"],
        "title": title_of(meta.get("project_id"), "claude", meta["session_id"]),
    }


def find_by_pty(pty_id: str) -> dict | None:
    """The suspended or running Claude session that holds this terminal id. Blocking."""
    from routes import terminal

    record = agent_suspend.all_records().get(pty_id)
    if record is not None and record.get("agent") == "claude" and record.get("session_id"):
        return _suspended_entry(pty_id, record)
    meta = terminal.live_pty_labels().get(pty_id)
    if meta and meta.get("agent") == "claude" and meta.get("session_id"):
        return _live_entry(pty_id, meta)
    return None


def list_entries() -> list[dict]:
    """Every Claude session that can be messaged, suspended or running. Blocking."""
    from routes import terminal

    found = {
        pty_id: _suspended_entry(pty_id, record)
        for pty_id, record in agent_suspend.all_records().items()
        if record.get("agent") == "claude" and record.get("session_id")
    }
    for pty_id, meta in terminal.live_pty_labels().items():
        if pty_id not in found and meta.get("agent") == "claude" and meta.get("session_id"):
            found[pty_id] = _live_entry(pty_id, meta)
    return list(found.values())


def check_switches() -> None:
    if not relay_settings.admin_allows_messaging():
        raise WakeRefused("admin_denied", "Your administrator has turned off agent messaging.")
    if not relay_settings.user_allows_messaging():
        raise WakeRefused("switched_off", "Agent messaging is switched off.")


def _candidate(entry: dict) -> dict:
    return {
        "session_id": entry["session_id"],
        "name": entry["title"] or entry["session_id"],
        "state": entry["state"],
        "project_id": entry["project_id"],
    }


async def _pty(pty_id: str):
    from routes import terminal

    return await asyncio.to_thread(terminal.get_pty_session, pty_id)


async def _resume(entry: dict, sender_name: str, preview: str) -> str:
    """Resume the suspended session in its own terminal id. Returns the terminal id that now holds it."""
    from fastapi import HTTPException
    from routes import generic_agent_routes

    record = entry["record"]
    repo = await asyncio.to_thread(_project_repo, record.get("project_id"))
    if not repo:
        raise WakeRefused("failed", "The project this agent belonged to no longer exists.")
    stored = await asyncio.to_thread(agent_sessions.find_session, repo, entry["agent"], entry["session_id"])
    if stored is None:
        raise WakeRefused("failed", "The stored session is gone, so it cannot be resumed.")
    req = generic_agent_routes.GenericAgentTerminalRequest(
        agent=entry["agent"],
        project_id=record["project_id"],
        repo_path=repo,
        resume_id=entry["session_id"],
    )
    try:
        result = await generic_agent_routes.resume_suspended(
            req, entry["pty_id"], clean(sender_name)[:NAME_MAX_CHARS], preview[:PREVIEW_CHARS]
        )
    except HTTPException as exc:
        raise WakeRefused("failed", f"The agent could not be resumed: {exc.detail}") from exc
    except Exception as exc:
        logger.warning("could not resume %s", entry["session_id"], exc_info=True)
        raise WakeRefused("failed", "The agent could not be resumed.") from exc
    return result["pty_session_id"]


def _ready_now(pty_id: str, pty_entry) -> str:
    """'ready', or what the agent is doing instead."""
    state = agent_state.read_states([pty_id]).get(pty_id)
    if not state:
        return "unknown"
    if state["state"] != "idle":
        return state["state"]
    if time.time() - getattr(pty_entry, "last_user_input", 0.0) < USER_TYPING_SECONDS:
        return "typing"
    try:
        output, _ = pty_entry.read_from(0)
        painted = BRACKETED_PASTE_ON in output or pty_entry.first_offset > 0
    except Exception:
        return "starting"
    return "ready" if painted else "starting"


async def _wait_ready(pty_id: str, timeout: float) -> None:
    """Wait until the agent reports idle and is taking pasted input. Never answers a prompt:
    an agent that is asking is waited on, not typed at."""
    deadline = time.monotonic() + timeout
    steady = 0
    last = "starting"
    while time.monotonic() < deadline:
        entry = await _pty(pty_id)
        if entry is None or entry.done:
            raise WakeRefused("failed", "The agent exited before it was ready.")
        last = await asyncio.to_thread(_ready_now, pty_id, entry)
        steady = steady + 1 if last == "ready" else 0
        if steady >= 2:
            return
        await asyncio.sleep(READY_POLL_SECONDS)
    reason = {
        "asking": "The agent is waiting for the user to answer a permission prompt.",
        "working": "The agent is busy with a turn.",
        "typing": "The user is typing in that terminal.",
    }.get(last, "The agent did not become ready in time.")
    raise WakeRefused("not_ready", reason)


async def _type_message(pty_id: str, text: str) -> None:
    from routes import terminal

    if not await asyncio.to_thread(terminal.write_pty_session, pty_id, f"\x1b[200~{text}\x1b[201~"):
        raise WakeRefused("failed", "The message could not be typed into the terminal.")
    await asyncio.sleep(PASTE_TO_ENTER_SECONDS)
    state = agent_state.read_states([pty_id]).get(pty_id)
    # Enter is only safe on an idle prompt; at a permission prompt it would answer it.
    if not state or state["state"] != "idle":
        raise WakeRefused("failed", "The agent changed state before the message was sent; it was typed but not submitted.")
    if not await asyncio.to_thread(terminal.write_pty_session, pty_id, "\r"):
        raise WakeRefused("failed", "The message could not be submitted.")


async def wake_and_deliver(
    sender: dict, target: str, message: str, *, allow_cross_project: bool = False
) -> dict:
    """Deliver one message to the named agent, waking it first when it is suspended.

    `sender` is {"name", "session_id", "project_id"} as known to the front door. Raises
    WakeRefused with a code and a reason when nothing was delivered; every refusal is audited."""
    try:
        return await _wake_and_deliver(sender, target, message, allow_cross_project)
    except WakeRefused as exc:
        await asyncio.to_thread(audit_refusal, sender, target, exc.code, exc.reason, message)
        raise


async def _wake_and_deliver(sender: dict, target: str, message: str, allow_cross_project: bool) -> dict:
    check_switches()
    frame(sender.get("name", ""), message)
    matches = await asyncio.to_thread(find_targets, target, sender.get("project_id"), allow_cross_project)
    if not matches:
        raise WakeRefused("not_found", "No suspended or running Claude agent with that name or id in this project.")
    if len(matches) > 1:
        raise WakeRefused(
            "ambiguous",
            "More than one agent has that name; choose one by session id.",
            candidates=[_candidate(m) for m in matches],
        )
    return await deliver_entry(sender, matches[0], message)


async def deliver_entry(
    sender: dict,
    entry: dict,
    message: str,
    *,
    spend_slot: bool = True,
    origin: str = "agent",
    before_type: Callable[[str], Awaitable[None]] | None = None,
    live_wait: float = LIVE_READY_SECONDS,
) -> dict:
    """Deliver one message to a session `find_targets` or `find_by_pty` returned, waking it
    first when it is suspended. The relay core passes spend_slot=False: it keeps its own limits.
    `before_type(pty_id)` runs once the session is awake and ready, just before the text is
    typed; it raises WakeRefused to stop the delivery. `live_wait` is how long to wait for a
    running session to finish its turn."""
    now = time.time()
    check_switches()
    text = frame(sender.get("name", ""), message, origin)
    if entry["session_id"] == sender.get("session_id") or entry["pty_id"] == sender.get("pty_id"):
        raise WakeRefused("invalid", "An agent cannot message itself.")
    if relay_settings.opted_out(f"pty:{entry['pty_id']}"):
        raise WakeRefused("opted_out", "That agent does not accept messages from other agents.")
    key = entry["session_id"]
    if not claim(key):
        raise WakeRefused("busy", "This agent is being woken, messaged or suspended right now; try again shortly.")
    try:
        if spend_slot:
            _spend_sender_slot(sender.get("pty_id") or sender.get("session_id") or sender.get("name", ""), now)
        if entry["state"] == "suspended":
            entry["record"] = agent_suspend.suspended_record(entry["pty_id"])
            if entry["record"] is None:
                raise WakeRefused("failed", "The agent is no longer suspended; try again.")
            pty_id = await _resume(entry, sender.get("name", ""), clean(message))
            try:
                await _wait_ready(pty_id, WAKE_READY_SECONDS)
            finally:
                # The record goes once the agent is running. One that died on the way up
                # keeps it, so the failure can be marked and the wake retried.
                running = await _pty(pty_id)
                if running is not None and not running.done:
                    await asyncio.to_thread(agent_suspend.forget, entry["pty_id"])
        else:
            pty_id = entry["pty_id"]
            if not agent_state.read_states([pty_id]).get(pty_id):
                raise WakeRefused("not_ready", "This agent does not report its state, so it cannot be messaged safely.")
            await _wait_ready(pty_id, live_wait)
        if before_type is not None:
            await before_type(pty_id)
        await _type_message(pty_id, text)
    except WakeRefused as exc:
        if entry["state"] == "suspended" and exc.code == "failed":
            await asyncio.to_thread(
                agent_suspend.mark_failed,
                entry["pty_id"],
                {"reason": exc.reason, "message": clean(message)[:PREVIEW_CHARS], "sender": clean(sender.get("name", "")), "at": now},
            )
        raise
    finally:
        release(key)
    await asyncio.to_thread(_audit, sender, entry, "delivered", clean(message), now)
    return {"status": "delivered", "woke": entry["state"] == "suspended", "target": _candidate(entry)}
