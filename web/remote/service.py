"""Headless session lifecycle. Calls only the SessionHost interface; the command layer
calls this."""

from __future__ import annotations

import inspect
import logging
import re
import time
from dataclasses import dataclass
from typing import Awaitable, Callable

from remote.session_host import HostError, Project, SessionHost

_log = logging.getLogger(__name__)

IDLE_SECONDS = 8 * 3600.0


class RemoteError(Exception):
    """A refusal with a reason that is safe to show the user."""


@dataclass
class Session:
    id: str
    pty_id: str
    project: Project
    short: str
    vendor_session_id: str | None
    created_at: float
    last_activity: float
    awaiting_since: float | None = None
    last_event_at: float = 0.0
    stopping: bool = False


@dataclass(frozen=True)
class Event:
    kind: str  # completed | input-required | failed | canceled
    session: Session
    text: str = ""


Subscriber = Callable[[Event], Awaitable[None] | None]


def _slug(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-") or "session"


class RemoteService:
    def __init__(
        self,
        host: SessionHost,
        default_project: Callable[[], Project | None],
        clock: Callable[[], float] = time.time,
        idle_seconds: float = IDLE_SECONDS,
    ):
        self._host = host
        self._default_project = default_project
        self._clock = clock
        self._idle = idle_seconds
        self._sessions: dict[str, Session] = {}
        self._subscribers: list[Subscriber] = []

    def subscribe(self, callback: Subscriber) -> None:
        self._subscribers.append(callback)

    async def _emit(self, kind: str, session: Session, text: str = "") -> None:
        for callback in list(self._subscribers):
            try:
                result = callback(Event(kind, session, text))
                if inspect.isawaitable(result):
                    await result
            except Exception:
                _log.warning("remote event subscriber failed", exc_info=True)

    def default_project(self) -> Project | None:
        return self._default_project()

    def list(self) -> list[Session]:
        return list(self._sessions.values())

    def get(self, session_id: str) -> Session:
        try:
            return self._sessions[session_id]
        except KeyError:
            raise RemoteError("No such session. Send `@gator list` to see the running ones.") from None

    def resolve(self, short: str) -> Session | None:
        short = short.lower()
        return next((s for s in self._sessions.values() if s.short == short), None)

    def _short_for(self, project: Project) -> str:
        base = _slug(project.name)
        taken = {s.short for s in self._sessions.values()}
        if base not in taken:
            return base
        n = 2
        while f"{base}-{n}" in taken:
            n += 1
        return f"{base}-{n}"

    async def start(self, project: Project, text: str) -> Session:
        try:
            spawned = await self._host.spawn(project)
        except HostError as exc:
            raise RemoteError(str(exc)) from exc
        now = self._clock()
        session = Session(
            id=f"pty:{spawned.pty_id}",
            pty_id=spawned.pty_id,
            project=project,
            short=self._short_for(project),
            vendor_session_id=spawned.vendor_session_id,
            created_at=now,
            last_activity=now,
        )
        self._sessions[session.id] = session
        await self._deliver(session, text)
        return session

    async def send(self, session_id: str, text: str) -> None:
        await self._deliver(self.get(session_id), text)

    async def _deliver(self, session: Session, text: str) -> None:
        sent_at = self._clock()
        try:
            await self._host.deliver(session.pty_id, text)
        except HostError as exc:
            raise RemoteError(str(exc)) from exc
        session.last_activity = self._clock()
        session.awaiting_since = sent_at

    async def stop(self, session_id: str) -> None:
        session = self.get(session_id)
        session.stopping = True
        try:
            await self._host.kill(session.pty_id)
        except HostError as exc:
            session.stopping = False
            raise RemoteError(str(exc)) from exc
        self._sessions.pop(session.id, None)
        await self._emit("canceled", session)

    async def stop_all(self) -> None:
        for session in self.list():
            try:
                await self.stop(session.id)
            except RemoteError:
                _log.warning("stop-all: could not stop %s", session.id, exc_info=True)

    async def output(self, session_id: str, since: int) -> tuple[str, int]:
        session = self.get(session_id)
        try:
            return await self._host.output(session.pty_id, since)
        except HostError as exc:
            raise RemoteError(str(exc)) from exc

    async def tick(self) -> None:
        """One pass: report exits, finished turns and questions; stop idle sessions."""
        for session in self.list():
            if session.stopping:
                continue
            if not await self._host.alive(session.pty_id):
                self._sessions.pop(session.id, None)
                await self._emit("failed", session, "The agent process exited.")
                continue
            if self._clock() - session.last_activity >= self._idle:
                try:
                    await self.stop(session.id)
                except RemoteError:
                    pass
                continue
            await self._check_state(session)

    async def _check_state(self, session: Session) -> None:
        state = await self._host.state(session.pty_id)
        if not state or state["at"] <= session.last_event_at:
            return
        if state["state"] == "asking":
            kind = "input-required"
        elif state["state"] == "idle" and session.awaiting_since is not None and state["at"] >= session.awaiting_since:
            kind = "completed"
        else:
            return
        session.last_event_at = state["at"]
        if kind == "completed":
            session.awaiting_since = None
        session.last_activity = max(session.last_activity, state["at"])
        await self._emit(kind, session, await self._host.last_message(session.pty_id))
