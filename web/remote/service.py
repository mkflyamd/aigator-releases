"""Headless session lifecycle. Calls only the SessionHost interface; the command layer
calls this."""

from __future__ import annotations

import inspect
import logging
import re
import time
from dataclasses import dataclass
from typing import Awaitable, Callable

from remote.guard import limit
from remote.session_host import HostError, Project, SessionHost

_log = logging.getLogger(__name__)

IDLE_SECONDS = 8 * 3600.0
STARTED = "started"
ADOPTED = "adopted"
ADOPTED_MISSES = 2


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
    waiting: bool = False
    last_event_at: float = 0.0
    stopping: bool = False
    kind: str = STARTED  # ADOPTED: someone else's session that Remote only watches, never closes
    name: str = ""
    misses: int = 0


@dataclass(frozen=True)
class Event:
    kind: str  # completed | input-required | failed | canceled | detached
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
        idle_seconds: float | Callable[[], float] = IDLE_SECONDS,
        channel: str = "default",
    ):
        self._channel = channel
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
        """The sessions Remote started. Adopted ones are watched, not listed: nothing here types into
        them, closes them or counts them, so every command that walks this list stays safe by shape."""
        return [s for s in self._sessions.values() if s.kind == STARTED]

    def watched(self, kind: str) -> list[Session]:
        return [s for s in self._sessions.values() if s.kind == kind]

    def get(self, session_id: str) -> Session:
        try:
            return self._sessions[session_id]
        except KeyError:
            raise RemoteError("No such session. Send `@gator list` to see the running ones.") from None

    def resolve(self, short: str) -> Session | None:
        short = short.lower()
        return next((s for s in self.list() if s.short == short), None)

    def adopt(self, pty_id: str, project: Project, name: str, vendor_session_id: str | None) -> Session:
        """Starts watching another agent's session after a message was typed into it, so the turn it
        answers with can be reported. It is never closed by Remote, and not persisted: a restart
        forgets it rather than adopting or killing what it did not start."""
        now = self._clock()
        session_id = f"pty:{pty_id}"
        session = self._sessions.get(session_id)
        if session is None:
            session = self._sessions[session_id] = Session(
                id=session_id,
                pty_id=pty_id,
                project=project,
                short=f"peer-{pty_id[:8]}",
                vendor_session_id=vendor_session_id,
                created_at=now,
                last_activity=now,
                kind=ADOPTED,
            )
        if session.kind != ADOPTED:
            raise RemoteError("That session was started by Remote control.")
        session.name = name
        session.last_activity = session.awaiting_since = now
        session.waiting = False
        return session

    def _short_for(self, project: Project) -> str:
        base = _slug(project.name)
        taken = {s.short for s in self._sessions.values()}
        if base not in taken:
            return base
        n = 2
        while f"{base}-{n}" in taken:
            n += 1
        return f"{base}-{n}"

    async def restore(self) -> None:
        """Rebuilds the session table from the host after a backend restart. Raises
        RemoteError when the host cannot be asked, so the caller retries rather than
        treat the table as empty."""
        try:
            restored = await self._host.restore(self._channel)
        except HostError as exc:
            raise RemoteError(str(exc)) from exc
        now = self._clock()
        for r in restored:
            session_id = f"pty:{r.pty_id}"
            if session_id in self._sessions:
                continue
            self._sessions[session_id] = Session(
                id=session_id,
                pty_id=r.pty_id,
                project=r.project,
                short=r.short,
                vendor_session_id=r.vendor_session_id,
                created_at=r.created_at or now,
                last_activity=now,
            )

    async def start(self, project: Project, text: str) -> Session:
        now = self._clock()
        short = self._short_for(project)
        labels = {"remote_channel": self._channel, "remote_short": short, "remote_created": str(now)}
        try:
            spawned = await self._host.spawn(project, labels)
        except HostError as exc:
            raise RemoteError(str(exc)) from exc
        session = Session(
            id=f"pty:{spawned.pty_id}",
            pty_id=spawned.pty_id,
            project=project,
            short=short,
            vendor_session_id=spawned.vendor_session_id,
            created_at=now,
            last_activity=now,
        )
        try:
            await self._deliver(session, text)
        except Exception:
            try:
                await self._host.kill(spawned.pty_id)
            except Exception:
                _log.warning("could not roll back %s after a failed first delivery", session.id, exc_info=True)
            raise
        self._sessions[session.id] = session
        return session

    async def send(self, session_id: str, text: str) -> None:
        await self._deliver(self.get(session_id), text)

    async def _deliver(self, session: Session, text: str) -> None:
        if session.kind != STARTED:
            raise RemoteError("Messages to another agent go through its name, not through Remote control.")
        try:
            await self._host.deliver(session.pty_id, text)
        except HostError as exc:
            raise RemoteError(str(exc)) from exc
        session.last_activity = session.awaiting_since = self._clock()
        session.waiting = False

    async def stop(self, session_id: str) -> None:
        session = self.get(session_id)
        if session.kind == ADOPTED:
            self._sessions.pop(session.id, None)
            await self._emit("detached", session)
            return
        session.stopping = True
        try:
            await self._host.kill(session.pty_id)
        except HostError as exc:
            session.stopping = False
            raise RemoteError(str(exc)) from exc
        self._sessions.pop(session.id, None)
        await self._emit("canceled", session)

    async def stop_all(self) -> tuple[list[Session], list[Session]]:
        """Returns (stopped, failed): only what was really stopped, and what is still running."""
        stopped: list[Session] = []
        failed: list[Session] = []
        for session in self.list():
            try:
                await self.stop(session.id)
            except RemoteError:
                _log.warning("stop-all: could not stop %s", session.id, exc_info=True)
                failed.append(session)
            else:
                stopped.append(session)
        return stopped, failed

    async def output(self, session_id: str, since: int) -> tuple[str, int]:
        session = self.get(session_id)
        try:
            return await self._host.output(session.pty_id, since)
        except HostError as exc:
            raise RemoteError(str(exc)) from exc

    async def tick(self) -> None:
        """One pass: report exits, finished turns and questions; stop idle sessions."""
        for session in list(self._sessions.values()):
            if session.stopping:
                continue
            if not await self._host.alive(session.pty_id):
                if session.kind == ADOPTED:
                    # A slow terminal host also reads as "not alive"; one miss is not an exit.
                    session.misses += 1
                    if session.misses < ADOPTED_MISSES:
                        continue
                    self._sessions.pop(session.id, None)
                    if session.awaiting_since is not None:
                        await self._emit("detached", session, "The agent process exited.")
                else:
                    self._sessions.pop(session.id, None)
                    await self._emit("failed", session, "The agent process exited.")
                continue
            session.misses = 0
            if self._clock() - session.last_activity >= limit(self._idle):
                if session.kind == ADOPTED:
                    self._sessions.pop(session.id, None)
                    await self._emit("detached", session)
                    continue
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
        # Another agent's own questions and turns are its owner's business; only what follows a
        # message sent from chat is reported.
        if session.kind == ADOPTED and (session.awaiting_since is None or state["at"] < session.awaiting_since):
            return
        if state["state"] == "asking":
            kind = "input-required"
            session.waiting = True
        elif state["state"] == "idle" and session.awaiting_since is not None and state["at"] >= session.awaiting_since:
            kind = "completed"
        else:
            return
        session.last_event_at = state["at"]
        if kind == "completed":
            session.awaiting_since = None
            session.waiting = False
        session.last_activity = max(session.last_activity, state["at"])
        text = await self._host.last_message(session.pty_id)
        if kind == "completed" and session.kind == ADOPTED:
            self._sessions.pop(session.id, None)  # watched for one answer; the next message adopts it again
        await self._emit(kind, session, text)
