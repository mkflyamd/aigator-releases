"""Headless session lifecycle. Calls only the SessionHost interface; the command layer
calls this.

A project has one lane: its remote session, live or asleep. The lane is stored (State), so it
outlives the process and a backend restart. The idle sweep suspends a quiet session to free its
memory; the lane then sleeps, and the next message wakes that same session by its id."""

from __future__ import annotations

import inspect
import logging
import re
import time
from dataclasses import dataclass
from typing import Awaitable, Callable

from remote.guard import limit
from remote.session_host import HostError, Project, SessionHost
from remote.state import State

_log = logging.getLogger(__name__)

IDLE_SECONDS = 8 * 3600.0
WAKE_MIN_INTERVAL = 30.0
LIVE, SLEEPING, FAILED = "live", "sleeping", "failed"


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
    state: str = LIVE
    waking: bool = False
    last_wake_at: float = float("-inf")
    failure: str = ""


@dataclass(frozen=True)
class Event:
    kind: str  # completed | input-required | failed | canceled | lost
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
        state: State | None = None,
    ):
        self._channel = channel
        self._store = state
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

    def lane_of(self, project_id: str) -> Session | None:
        return next((s for s in self._sessions.values() if s.project.id == project_id), None)

    def _labels(self, session: Session) -> dict[str, str]:
        return {
            "remote_channel": self._channel,
            "remote_short": session.short,
            "remote_created": str(session.created_at),
        }

    def _persist(self, session: Session) -> None:
        if self._store is None or session.id not in self._sessions:
            return
        self._store.put_lane(
            self._channel,
            {
                "project_id": session.project.id,
                "name": session.project.name,
                "agent": session.project.agent,
                "repo_path": session.project.repo_path,
                "pty_id": session.pty_id,
                "short": session.short,
                "vendor_session_id": session.vendor_session_id,
                "created_at": session.created_at,
                "last_activity": session.last_activity,
                "state": session.state,
                "failure": session.failure,
            },
        )

    def _forget(self, session: Session) -> None:
        self._sessions.pop(session.id, None)
        if self._store is not None:
            lane = self._store.lanes(self._channel).get(session.project.id)
            if lane is None or lane["pty_id"] == session.pty_id:
                self._store.drop_lane(self._channel, session.project.id)

    async def restore(self) -> None:
        """Rebuilds the session table after a backend restart: the live sessions from the host, the
        sleeping ones from the stored lanes. Raises RemoteError when the host cannot be asked, so
        the caller retries rather than treat the table as empty."""
        try:
            restored = await self._host.restore(self._channel)
        except HostError as exc:
            raise RemoteError(str(exc)) from exc
        now = self._clock()
        lanes = self._store.lanes(self._channel) if self._store is not None else {}
        for r in restored:
            session_id = f"pty:{r.pty_id}"
            if session_id in self._sessions or self.lane_of(r.project.id) is not None:
                continue
            lane = lanes.get(r.project.id) or {}
            same = lane.get("pty_id") == r.pty_id
            session = Session(
                id=session_id,
                pty_id=r.pty_id,
                project=r.project,
                short=r.short,
                vendor_session_id=r.vendor_session_id,
                created_at=r.created_at or now,
                last_activity=lane.get("last_activity", now) if same else now,
            )
            self._sessions[session_id] = session
            self._persist(session)
        for project_id, lane in lanes.items():
            if self.lane_of(project_id) is not None:
                continue
            session = self._session_from_lane(lane, now)
            if await self._host.alive(session.pty_id):
                session.state = LIVE
            elif await self._host.sleeping(session.pty_id):
                session.state = FAILED if lane["state"] == FAILED else SLEEPING
            elif lane["state"] == FAILED:
                session.state = FAILED
            else:
                self._forget(session)
                continue
            self._sessions[session.id] = session
            self._persist(session)

    @staticmethod
    def _session_from_lane(lane: dict, now: float) -> Session:
        project = Project(
            id=lane["project_id"],
            name=lane.get("name") or lane["project_id"],
            repo_path=lane["repo_path"],
            agent=lane.get("agent") or "claude",
        )
        return Session(
            id=f"pty:{lane['pty_id']}",
            pty_id=lane["pty_id"],
            project=project,
            short=lane["short"],
            vendor_session_id=lane.get("vendor_session_id"),
            created_at=lane.get("created_at") or now,
            last_activity=lane.get("last_activity") or now,
            state=lane["state"],
            failure=lane.get("failure") or "",
        )

    async def start(self, project: Project, text: str) -> Session:
        existing = self.lane_of(project.id)
        if existing is not None:
            raise RemoteError(
                f"{existing.short} already has a session in this project. "
                f"Send `{existing.short}: your message` to use it, or `stop {existing.short}` first."
            )
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
        self._persist(session)
        return session

    async def send(self, session_id: str, text: str) -> None:
        await self._deliver(self.get(session_id), text)

    async def _deliver(self, session: Session, text: str) -> None:
        try:
            await self._host.deliver(session.pty_id, text)
        except HostError as exc:
            raise RemoteError(str(exc)) from exc
        session.last_activity = session.awaiting_since = self._clock()
        session.waiting = False
        self._persist(session)

    async def needs_wake(self, session: Session) -> bool:
        """True when the lane has no running process. A lane the last tick still shows as live is
        checked now: the idle sweep may have suspended it since."""
        if session.state == LIVE and not session.waking and not session.stopping:
            if not await self._host.alive(session.pty_id) and await self._host.sleeping(session.pty_id):
                session.state = SLEEPING
                self._persist(session)
        return session.state != LIVE

    def begin_wake(self, session: Session) -> None:
        """Claims the lane for one wake, or refuses. Synchronous, so two messages in a row cannot
        both start one: the second finds `waking` set."""
        if session.state == FAILED:
            raise RemoteError(
                f"{session.failure or 'This session cannot be woken.'} "
                f"Send `stop {session.short}`, then send your message again to start a new one."
            )
        if session.waking:
            raise RemoteError(f"{session.short} is already waking up. Give it a moment.")
        wait = WAKE_MIN_INTERVAL - (self._clock() - session.last_wake_at)
        if wait > 0:
            raise RemoteError(f"{session.short} could not be woken a moment ago. Try again in {int(wait) + 1} seconds.")
        session.waking = True
        session.last_wake_at = self._clock()

    async def wake(self, session: Session, text: str, proceed: Callable[[], bool] = lambda: True) -> None:
        """Wakes the sleeping session by its own id, then delivers `text`. Call begin_wake first.
        `proceed` is asked once it is awake: a no stops the delivery (Remote control was turned
        off meanwhile). Any failure raises and leaves the lane as it was (or failed, when retrying
        cannot help): a fresh session is never started in its place."""
        try:
            try:
                await self._host.wake(session.pty_id, session.project, self._labels(session))
            except HostError as exc:
                if exc.permanent:
                    session.state, session.failure = FAILED, str(exc)
                    self._persist(session)
                raise RemoteError(str(exc)) from exc
            if session.stopping:
                raise RemoteError(f"{session.short} was stopped while it woke, so nothing was sent.")
            session.state, session.failure = LIVE, ""
            self._persist(session)
            if not proceed():
                raise RemoteError("Remote control was turned off while it woke, so nothing was sent.")
            await self._deliver(session, text)
        finally:
            session.waking = False

    async def stop(self, session_id: str) -> None:
        """Ends the lane for good, whether it is running, asleep or failed: the process is closed
        and its saved record dropped, so nothing is left to resume."""
        session = self.get(session_id)
        session.stopping = True
        try:
            await self._host.kill(session.pty_id)
        except HostError as exc:
            session.stopping = False
            raise RemoteError(str(exc)) from exc
        self._forget(session)
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
        for session in self.list():
            if session.stopping or session.waking:
                continue
            if await self._host.alive(session.pty_id):
                if session.state == SLEEPING:
                    session.state = LIVE
                    self._persist(session)
            elif session.state != FAILED and await self._host.sleeping(session.pty_id):
                if session.state == LIVE:
                    session.state = SLEEPING
                    self._persist(session)
            elif session.state != FAILED:
                self._forget(session)
                if session.state == LIVE:
                    await self._emit("failed", session, "The agent process exited.")
                else:
                    await self._emit("lost", session)
                continue
            if self._clock() - session.last_activity >= limit(self._idle):
                try:
                    await self.stop(session.id)
                except RemoteError:
                    pass
                continue
            if session.state == LIVE:
                await self._check_state(session)

    async def _check_state(self, session: Session) -> None:
        state = await self._host.state(session.pty_id)
        if not state or state["at"] <= session.last_event_at:
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
        self._persist(session)
        await self._emit(kind, session, await self._host.last_message(session.pty_id))
