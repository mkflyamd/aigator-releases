"""The relay core: one place that decides whether a message may go, and records what happened.

Adapters (terminal agents, chat tabs) only deliver. Everything else lives here: the admin
and user switches, sender stamping, idempotency, hop depth, rate limits, links, audit.
A relayed message never widens what its target may do; a refusal is final for that message.
"""

from __future__ import annotations

import asyncio
import json
import logging
import threading
import time
from collections import OrderedDict
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

import agent_suspend
import agent_wake

from . import settings
from .model import Endpoint, Task, TaskState, iso, new_id

logger = logging.getLogger(__name__)

HOUR = 3600.0
MAX_HOPS = 16
UNLINKED_LIMIT = 5
LINK_LIMIT = 30
REPEAT_LIMIT = 3
MAX_LINK_SECONDS = 24 * HOUR
DEFAULT_LINK_SECONDS = 8 * HOUR
TASKS_KEEP = 500
AUDIT_KEEP = 1000
PREVIEW_CHARS = 200
COUNTED_STATES = (TaskState.SUBMITTED, TaskState.WORKING, TaskState.COMPLETED)

SUBMIT = "submit"
DRAFT = "draft"


class Refused(Exception):
    """An adapter or the core will not deliver. `permanent` refusals become REJECTED, the rest FAILED."""

    def __init__(self, code: str, reason: str, *, permanent: bool = False, **extra):
        super().__init__(reason)
        self.code = code
        self.reason = reason
        self.permanent = permanent
        self.extra = extra


class Adapter(Protocol):
    """One kind of endpoint. It finds endpoints by name or id and hands a message to one."""

    kind: str

    async def resolve(self, ref: str, sender: Endpoint, *, allow_cross_project: bool) -> list[Endpoint]: ...

    async def deliver(self, sender: Endpoint, target: Endpoint, text: str, mode: str) -> str | tuple[str, dict]:
        """Returns how it arrived, "submitted" or "drafted", optionally with extra details
        for the task. Raises Refused when it did not."""
        ...


@dataclass
class Link:
    """The user's standing approval for two endpoints to message each other until it expires."""

    id: str
    a: Endpoint
    b: Endpoint
    expires_at: float
    stopped: bool = False
    paused: str = ""
    settled: frozenset[str] = frozenset()

    def other(self, endpoint_id: str) -> Endpoint | None:
        if endpoint_id == self.a.id:
            return self.b
        if endpoint_id == self.b.id:
            return self.a
        return None

    def active(self, now: float) -> bool:
        return not self.stopped and now < self.expires_at

    def as_dict(self, now: float) -> dict:
        return {
            "id": self.id,
            "a": self.a.as_dict(),
            "b": self.b.as_dict(),
            "expires_at": iso(self.expires_at),
            "active": self.active(now),
            "paused": self.paused,
        }


def audit_file() -> Path:
    return agent_suspend.STATE_FILE.parent / "relay" / "audit.jsonl"


_audit_lock = threading.Lock()


def recent_audit(limit: int = 50) -> list[dict]:
    try:
        lines = audit_file().read_text(encoding="utf-8").splitlines()
    except OSError:
        return []
    found: list[dict] = []
    for line in lines[-limit:]:
        try:
            found.append(json.loads(line))
        except ValueError:
            continue
    return found[::-1]


def write_audit(line: dict) -> None:
    path = audit_file()
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with _audit_lock:
            lines = path.read_text(encoding="utf-8").splitlines() if path.exists() else []
            lines = [*lines[-(AUDIT_KEEP - 1) :], json.dumps(line)]
            agent_suspend._write_atomic(path, "\n".join(lines) + "\n")
    except OSError:
        logger.warning("could not write the relay audit line", exc_info=True)


class Relay:
    def __init__(self, *, clock=time.time, audit=write_audit):
        self._clock = clock
        self._audit = audit
        self._adapters: list[Adapter] = []
        self._tasks: OrderedDict[str, Task] = OrderedDict()
        self._by_message: dict[tuple[str, str], str] = {}
        self._links: dict[str, Link] = {}
        self._busy: set[str] = set()
        self._running: dict[str, asyncio.Future] = {}
        self._canceled: set[str] = set()
        self._lock = threading.Lock()

    def register(self, adapter: Adapter) -> None:
        self._adapters.append(adapter)

    def task(self, task_id: str) -> dict | None:
        found = self._tasks.get(task_id)
        return found.as_a2a() if found else None

    def links(self) -> list[dict]:
        now = self._clock()
        return [link.as_dict(now) for link in self._links.values() if link.active(now)]

    def create_link(self, a: Endpoint, b: Endpoint, seconds: float = DEFAULT_LINK_SECONDS) -> Link:
        """Only a user action calls this. A link is the standing approval for the pair."""
        if a.id == b.id:
            raise ValueError("A link needs two different endpoints.")
        link = Link(new_id(), a, b, self._clock() + max(1.0, min(float(seconds), MAX_LINK_SECONDS)))
        self._links[link.id] = link
        self._audit({"at": iso(self._clock()), "event": "link_created", "link": link.id, "a": a.id, "b": b.id})
        return link

    def resume_link(self, link_id: str) -> bool:
        link = self._links.get(link_id)
        if link is None or not link.active(self._clock()):
            return False
        link.settled = frozenset(t.id for t in self._tasks.values() if t.context_id == f"link:{link.id}")
        link.paused = ""
        return True

    def stop_link(self, link_id: str) -> bool:
        """Cancel what is pending on the link first, then end it."""
        link = self._links.get(link_id)
        if link is None:
            return False
        self._cancel_pending(lambda task: task.context_id == f"link:{link.id}")
        link.stopped = True
        self._audit({"at": iso(self._clock()), "event": "link_stopped", "link": link.id})
        return True

    def stop_all(self) -> None:
        self._cancel_pending(lambda task: True)
        for link in self._links.values():
            link.stopped = True
        self._audit({"at": iso(self._clock()), "event": "stop_all"})

    def _cancel_pending(self, matches) -> None:
        for task_id, runner in list(self._running.items()):
            task = self._tasks.get(task_id)
            if task is not None and not runner.done() and matches(task):
                self._canceled.add(task_id)
                task.state, task.code, task.reason = TaskState.CANCELED, "canceled", "Stopped by the user."
                runner.cancel()

    async def submit(
        self, sender: Endpoint, target_ref: str, text: str, *, message_id: str | None = None, mode: str = SUBMIT
    ) -> dict:
        """An agent-initiated message. It goes over an active link when the target is the other
        end of one the sender has; otherwise it is same project only."""
        link = self._link_to(sender, target_ref)
        if link is not None:
            return await self._run(sender, None, link.id, text, message_id or new_id(), SUBMIT)
        return await self._run(sender, target_ref, None, text, message_id or new_id(), mode)

    def _link_to(self, sender: Endpoint, ref: str) -> Link | None:
        wanted = agent_wake.clean(ref).casefold()
        if not wanted:
            return None
        now = self._clock()
        for link in self._links.values():
            other = link.other(sender.id)
            if other is not None and link.active(now) and wanted in (other.id.casefold(), other.name.casefold()):
                return link
        return None

    async def send_on_link(
        self, link_id: str, sender: Endpoint, text: str, *, message_id: str | None = None
    ) -> dict:
        """A message between the two ends of a link. Delivery is `submit`: the link is the approval."""
        return await self._run(sender, None, link_id, text, message_id or new_id(), SUBMIT)

    def _hop_of(self, task: Task) -> int:
        """One more than the last message the sender received in this conversation; the relay
        works it out, a caller cannot supply it."""
        for earlier in reversed(self._tasks.values()):
            if earlier is not task and earlier.context_id == task.context_id and earlier.target:
                if earlier.target.id == task.sender.id:
                    return earlier.hop + 1
        return 1

    def _make_task(self, sender: Endpoint, text: str, message_id: str, context_id: str, now: float) -> Task:
        task = Task(new_id(), context_id, message_id, sender, None, text, 1, now)
        self._tasks[task.id] = task
        self._by_message[(sender.id, message_id)] = task.id
        surplus = len(self._tasks) - TASKS_KEEP
        if surplus > 0:
            for old in [t for t in self._tasks.values() if self._evictable(t, now)][:surplus]:
                del self._tasks[old.id]
                self._by_message.pop((old.sender.id, old.message_id), None)
        return task

    def _evictable(self, task: Task, now: float) -> bool:
        """A task still in flight, or one the hourly limits still count, must stay."""
        if task.id in self._running:
            return False
        return not (now - task.created_at < HOUR and task.state in COUNTED_STATES)

    def _finish(self, task: Task, state: TaskState, code: str, reason: str, now: float) -> dict:
        if task.id in self._canceled:
            self._canceled.discard(task.id)
            state, code, reason = TaskState.CANCELED, "canceled", "Stopped by the user."
        task.state, task.code, task.reason = state, code, reason
        line = {
            "at": iso(now),
            "event": "message",
            "task": task.id,
            "context": task.context_id,
            "sender": task.sender.id,
            "target": task.target.id if task.target else "",
            "state": state.value,
            "code": code,
            "reason": reason,
            "hop": task.hop,
        }
        # Text that was refused may be sensitive: only a delivered message keeps a preview.
        if state is TaskState.WORKING:
            line["message"] = task.text[:PREVIEW_CHARS]
        else:
            line["message_bytes"] = len(task.text.encode("utf-8"))
        self._audit(line)
        return task.as_a2a()

    def _refuse(self, task: Task, code: str, reason: str, now: float, *, permanent: bool = True, **extra) -> dict:
        task.extra.update(extra)
        return self._finish(task, TaskState.REJECTED if permanent else TaskState.FAILED, code, reason, now)

    def _count(self, task: Task, now: float, *, on_link: bool, settled: frozenset[str] = frozenset()) -> int:
        """Messages this hour that were not refused or failed, the current one included.
        Those the user already settled by resuming the link do not count again."""
        if on_link:
            same = lambda t: t.context_id == task.context_id and t.id not in settled  # noqa: E731
        else:
            same = lambda t: t.sender.id == task.sender.id and not t.context_id.startswith("link:")  # noqa: E731
        return sum(1 for t in self._tasks.values() if now - t.created_at < HOUR and t.state in COUNTED_STATES and same(t))

    def _repeated(self, task: Task, settled: frozenset[str] = frozenset()) -> bool:
        earlier = [
            t
            for t in self._tasks.values()
            if t is not task and t.context_id == task.context_id and t.sender.id == task.sender.id and t.id not in settled
        ]
        tail = earlier[-(REPEAT_LIMIT - 1) :]
        return len(tail) == REPEAT_LIMIT - 1 and all(t.text == task.text for t in tail)

    async def _run(
        self,
        sender: Endpoint,
        target_ref: str | None,
        link_id: str | None,
        text: str,
        message_id: str,
        mode: str,
    ) -> dict:
        now = self._clock()
        link = self._links.get(link_id) if link_id else None
        cleaned = agent_wake.clean(text)
        with self._lock:
            known = self._by_message.get((sender.id, message_id))
            if known and known in self._tasks:
                return self._tasks[known].as_a2a()
            task = self._make_task(sender, cleaned, message_id, f"link:{link.id}" if link else "", now)

        if link_id is not None and (link is None or not link.active(now) or link.other(sender.id) is None):
            return self._refuse(task, "no_link", "There is no active link for these agents.", now)
        if not settings.admin_allows_messaging():
            return self._refuse(task, "admin_denied", "Your administrator has turned off agent messaging.", now)
        if not settings.user_allows_messaging():
            return self._refuse(task, "switched_off", "Agent messaging is switched off.", now)
        if not cleaned:
            return self._refuse(task, "invalid", "The message is empty.", now)
        if len(cleaned.encode("utf-8")) > agent_wake.MESSAGE_MAX_BYTES:
            return self._refuse(
                task, "invalid", f"The message is longer than {agent_wake.MESSAGE_MAX_BYTES} bytes.", now
            )
        if link is not None and link.paused:
            return self._refuse(task, "link_paused", "This link is paused. The user can resume it in Settings.", now)

        if link is not None:
            matches = [link.other(sender.id)]
            allow_cross_project = True
        else:
            matches = []
            for adapter in self._adapters:
                matches += await adapter.resolve(target_ref or "", sender, allow_cross_project=False)
            allow_cross_project = False
        if not matches:
            return self._refuse(
                task, "not_found", "No agent with that name or id in this project.", now, permanent=False
            )
        if len(matches) > 1:
            return self._refuse(
                task, "ambiguous", "More than one agent has that name; choose one by id.", now, permanent=False,
                candidates=[m.as_dict() for m in matches],
            )
        target = matches[0]
        task.target = target
        if link is None:
            task.context_id = "pair:" + "|".join(sorted((sender.id, target.id)))
        task.hop = self._hop_of(task)
        if target.id == sender.id:
            return self._refuse(task, "invalid", "An agent cannot message itself.", now)
        if not allow_cross_project and sender.project_id != target.project_id:
            return self._refuse(task, "cross_project", "Agents can only message agents in their own project.", now)
        if settings.opted_out(target.id):
            return self._refuse(task, "opted_out", "That agent does not accept messages from other agents.", now)
        if task.hop > MAX_HOPS:
            return self._refuse(task, "hop_limit", "This conversation went back and forth too many times.", now)

        if link is not None:
            if self._repeated(task, link.settled):
                link.paused = "repeated"
                return self._refuse(task, "repeated", "The same message was sent several times; the link is paused.", now)
            if self._count(task, now, on_link=True, settled=link.settled) > LINK_LIMIT:
                link.paused = "limit_reached"
                return self._refuse(task, "limit_reached", "This link reached its hourly limit and is paused.", now)
        elif self._count(task, now, on_link=False) > UNLINKED_LIMIT:
            return self._refuse(
                task, "rate_limited", f"At most {UNLINKED_LIMIT} messages an hour per agent.", now
            )

        adapter = next((a for a in self._adapters if a.kind == target.kind), None)
        if adapter is None:
            return self._refuse(task, "no_adapter", "That kind of agent cannot receive messages yet.", now, permanent=False)
        with self._lock:
            if target.id in self._busy:
                return self._refuse(task, "busy", "That agent is being messaged right now; try again shortly.", now, permanent=False)
            self._busy.add(target.id)
        task.state = TaskState.WORKING
        runner = asyncio.ensure_future(adapter.deliver(sender, target, cleaned, mode))
        self._running[task.id] = runner
        try:
            outcome = await runner
            task.delivery, details = outcome if isinstance(outcome, tuple) else (outcome, {})
            task.extra.update(details)
        except asyncio.CancelledError:
            if task.id in self._canceled:
                return self._finish(task, TaskState.CANCELED, "canceled", "Stopped by the user.", now)
            raise
        except Refused as exc:
            return self._refuse(task, exc.code, exc.reason, now, permanent=exc.permanent, **exc.extra)
        except Exception:
            logger.exception("relay delivery failed")
            return self._refuse(task, "error", "AI Gator could not deliver the message.", now, permanent=False)
        finally:
            self._running.pop(task.id, None)
            with self._lock:
                self._busy.discard(target.id)
        return self._finish(task, TaskState.WORKING, "", "", now)
