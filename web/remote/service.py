"""Headless session lifecycle. Calls only the SessionHost interface; the command layer
calls this.

A project has one lane: its remote session, live or asleep. The lane is stored (State), so it
outlives the process and a backend restart. The idle sweep suspends a quiet session to free its
memory; the lane then sleeps, and the next message wakes that same session by its id. A sleeping
lane is kept until `stop`, Remote control turning off, or the 12-hour switch: only a live lane
that stays quiet past the idle limit is stopped."""

from __future__ import annotations

import asyncio
import inspect
import logging
import re
import time
from dataclasses import dataclass, field
from typing import Awaitable, Callable

from remote import commands
from remote.guard import limit
from remote.session_host import HostError, Project, RestoredSession, SessionHost
from remote.state import State

_log = logging.getLogger(__name__)

IDLE_SECONDS = 8 * 3600.0
WAKE_MIN_INTERVAL = 30.0
LIVE, SLEEPING, FAILED = "live", "sleeping", "failed"


class RemoteError(Exception):
    """A refusal with a reason that is safe to show the user. `permanent` means trying again
    cannot help."""

    def __init__(self, message: str, permanent: bool = False):
        super().__init__(message)
        self.permanent = permanent


class Refusal(RemoteError):
    """A RemoteError whose text is already a finished chat message."""


class Asleep(RemoteError):
    """The lane was asleep when the message reached it: wake it, then send."""


class Aborted(RemoteError):
    """A wake that was called off (the lane was stopped, or Remote control turned off): nothing
    went wrong, so nothing is reported."""


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
    wake_task: asyncio.Task | None = field(default=None, repr=False, compare=False)
    wake_cancelled: bool = False
    wake_delivering: bool = False


@dataclass(frozen=True)
class Event:
    kind: str  # completed | input-required | failed | canceled | lost | duplicate
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
            raise Refusal(commands.session_not_found(session_id)) from None

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

    def several(self, session: Session) -> bool:
        """True while more than one session is live, counting one that has just left the table."""
        return len({s.id for s in self._sessions.values()} | {session.id}) > 1

    def _copy(self, build, session: Session, *args, **kwargs) -> str:
        return build(session.short, *args, project=session.project.name, several=self.several(session), **kwargs)

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
            await self._restore()
        except HostError as exc:
            raise RemoteError(str(exc)) from exc

    async def _restore(self) -> None:
        restored = await self._host.restore(self._channel)
        now = self._clock()
        lanes = self._store.lanes(self._channel) if self._store is not None else {}
        by_project: dict[str, list[RestoredSession]] = {}
        for r in restored:
            by_project.setdefault(r.project.id, []).append(r)
        for project_id, found in by_project.items():
            if self.lane_of(project_id) is not None:
                continue
            lane = lanes.get(project_id) or {}
            keep = next((r for r in found if r.pty_id == lane.get("pty_id")), found[-1])
            for extra in found:
                if extra is not keep:
                    await self._report_duplicate(extra, now)
            if lane and lane["pty_id"] != keep.pty_id:
                _log.warning(
                    "remote lane %s for %s was %s; the running terminal %s replaces it",
                    lane["short"], project_id, lane["state"], keep.pty_id,
                )
                await self._host.kill(lane["pty_id"])
            same = lane.get("pty_id") == keep.pty_id
            session = Session(
                id=f"pty:{keep.pty_id}",
                pty_id=keep.pty_id,
                project=keep.project,
                short=keep.short,
                vendor_session_id=keep.vendor_session_id,
                created_at=keep.created_at or now,
                last_activity=lane.get("last_activity", now) if same else now,
            )
            self._sessions[session.id] = session
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
            elif await self._host.saved(session.project, session.vendor_session_id):
                # Its process is gone (the computer restarted) but the agent's own session is
                # on disk, and a wake resumes it from the lane: it is asleep, not lost.
                session.state = SLEEPING
            else:
                self._forget(session)
                continue
            self._sessions[session.id] = session
            self._persist(session)

    async def _report_duplicate(self, extra: RestoredSession, now: float) -> None:
        """A second running terminal for a project that already has a lane. It is left running,
        and said out loud: nothing in chat can manage it."""
        _log.warning("remote terminal %s is a second one for project %s; left running", extra.pty_id, extra.project.id)
        stray = Session(
            id=f"pty:{extra.pty_id}",
            pty_id=extra.pty_id,
            project=extra.project,
            short=extra.short,
            vendor_session_id=extra.vendor_session_id,
            created_at=extra.created_at or now,
            last_activity=now,
        )
        await self._emit("duplicate", stray)

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
            raise Refusal(self._copy(commands.already_has_session, existing))
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
        """Types `text` into a running session. A failure is looked at again: the idle sweep may
        have suspended the process in the meantime, and then the message needs a wake, not an error."""
        session = self.get(session_id)
        try:
            await self._deliver(session, text)
        except Refusal:
            raise
        except RemoteError:
            if await self.needs_wake(session):
                raise Asleep(f"{session.short} is asleep.") from None
            raise

    async def _deliver(self, session: Session, text: str) -> None:
        try:
            await self._host.deliver(session.pty_id, text)
        except HostError as exc:
            raise RemoteError(str(exc), exc.permanent) from exc
        session.last_activity = session.awaiting_since = self._clock()
        session.waiting = False
        self._persist(session)

    async def needs_wake(self, session: Session) -> bool:
        """True when the lane has no running process or is being woken. The host is asked, never
        guessed: the idle sweep may have suspended a lane the last tick showed as live, and a lane
        shown as asleep may have been resumed by hand."""
        if session.waking or session.stopping:
            return True
        try:
            alive = await self._host.alive(session.pty_id)
            sleeping = not alive and session.state == LIVE and await self._host.sleeping(session.pty_id)
        except HostError as exc:
            raise RemoteError(str(exc)) from exc
        if alive and session.state == SLEEPING:
            session.state, session.failure = LIVE, ""
            self._persist(session)
        elif sleeping:
            session.state = SLEEPING
            self._persist(session)
        return session.state != LIVE

    def begin_wake(self, session: Session) -> None:
        """Claims the lane for one wake, or refuses. Synchronous, so two messages in a row cannot
        both start one: the second finds `waking` set."""
        if session.state == FAILED:
            raise Refusal(
                self._copy(
                    commands.wake_failed, session, session.failure or "This session cannot be woken.", permanent=True
                )
            )
        if session.waking:
            raise Refusal(self._copy(commands.still_waking, session))
        wait = WAKE_MIN_INTERVAL - (self._clock() - session.last_wake_at)
        if wait > 0:
            raise Refusal(self._copy(commands.wake_too_soon, session, wait))
        session.wake_cancelled = False
        session.waking = True
        session.last_wake_at = self._clock()

    def attach_wake(self, session: Session, task: asyncio.Task) -> None:
        session.wake_task = task

    def abort_wakes(self) -> None:
        """Calls off every wake in progress. One that is still bringing the process up stops at its
        next check and closes it again; one that is already typing its message is left to finish."""
        for session in self._sessions.values():
            if session.waking:
                session.wake_cancelled = True

    async def wake(self, session: Session, text: str, proceed: Callable[[], bool] = lambda: True) -> None:
        """Wakes the sleeping session by its own id, then delivers `text`. Call begin_wake first.
        `proceed` is asked before the process is started and once it is awake: a no stops the wake
        (Remote control was turned off meanwhile). Any failure raises and leaves the lane as it was
        (or failed, when retrying cannot help): a fresh session is never started in its place."""

        def cancelled() -> bool:
            return session.stopping or session.wake_cancelled

        try:
            if cancelled() or not proceed():
                raise Aborted(session.short)
            try:
                await self._host.wake(
                    session.pty_id, session.project, self._labels(session), session.vendor_session_id, cancelled
                )
            except HostError as exc:
                if cancelled():
                    raise Aborted(session.short) from exc
                if exc.permanent:
                    session.state, session.failure = FAILED, str(exc)
                    self._persist(session)
                raise RemoteError(str(exc), exc.permanent) from exc
            if session.stopping:
                # The process came up after the stop asked for it to go: it ends here, whatever
                # else the stop does, so nothing is left running.
                try:
                    await self._host.kill(session.pty_id)
                except HostError:
                    _log.warning("could not close %s after a stop that raced its wake", session.id, exc_info=True)
                raise Aborted(session.short)
            session.state, session.failure = LIVE, ""
            self._persist(session)
            if cancelled() or not proceed():
                raise Aborted(session.short)
            session.wake_delivering = True
            await self._deliver(session, text)
        finally:
            session.waking = session.wake_delivering = False

    async def stop(self, session_id: str) -> None:
        """Ends the lane for good, whether it is running, asleep or failed: a wake in progress is
        waited for (or cut off, once it is only typing), the process is closed and its saved record
        dropped, so nothing is left to resume."""
        session = self.get(session_id)
        session.stopping = True
        task = session.wake_task
        if task is not None and not task.done():
            if session.wake_delivering:
                task.cancel()
            await asyncio.wait({task})
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
        """One pass: report exits, finished turns and questions; stop idle live sessions. A sleeping
        lane never expires on idle: it costs nothing, and stays until it is stopped."""
        for session in self.list():
            if session.stopping or session.waking:
                continue
            try:
                alive = await self._host.alive(session.pty_id)
                sleeping = not alive and await self._host.sleeping(session.pty_id)
                saved = (
                    not alive
                    and not sleeping
                    and session.state == SLEEPING
                    and await self._host.saved(session.project, session.vendor_session_id)
                )
            except HostError:
                _log.warning("remote tick: could not ask the host about %s; leaving it", session.id, exc_info=True)
                continue
            if alive:
                if session.state == SLEEPING:
                    session.state, session.failure = LIVE, ""
                    self._persist(session)
            elif session.state == FAILED or saved:
                pass
            elif sleeping:
                if session.state == LIVE:
                    session.state = SLEEPING
                    self._persist(session)
            else:
                self._forget(session)
                if session.state == LIVE:
                    await self._emit("failed", session, "The agent process exited.")
                else:
                    await self._emit("lost", session)
                continue
            if session.state != LIVE:
                continue
            if self._clock() - session.last_activity >= limit(self._idle):
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
