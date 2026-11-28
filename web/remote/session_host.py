"""Where remote sessions run. The service calls this interface only, so a server-hosted
tier or the cross-agent relay's terminal adapter can wrap or replace LocalPtyHost."""

from __future__ import annotations

import asyncio
import logging
import re
import time
from dataclasses import dataclass
from typing import Protocol

_log = logging.getLogger(__name__)

AGENT = "claude"
_TRANSCRIPT_TRIES = 4
_TRANSCRIPT_WAIT = 0.5
_ANSI = re.compile(r"\x1b\[[0-?]*[ -/]*[@-~]|\x1b\][^\x07\x1b]*(?:\x07|\x1b\\)|\x1b[@-_]")
WOKEN_BY = "Remote control"
PROMPT_CHECK_SECONDS = 3.0
# Claude Code asks this before resuming a large old session; the wording is from its own dialog.
RESUME_PROMPT = re.compile(r"Resume from summary|Resume full session as-is|This session is .{1,40} old and .{1,20} tokens")
IN_USE_MESSAGE = "Someone is using that session in AI Gator right now, so nothing was sent. Send it again when they are done."
OPEN_ELSEWHERE_MESSAGE = (
    "That session is open in another terminal on this computer, so it was not woken. "
    "Close it there, or keep using it there."
)
RESUME_PROMPT_MESSAGE = (
    "Claude is asking how to resume this large session (from a summary or in full), "
    "and it will not take a message until someone answers. Nothing was sent. "
    "Resume it once from the Code tab in AI Gator and choose there."
)


class HostError(Exception):
    """The host could not do what was asked; the message is for the user. `permanent` means
    trying again cannot help (the saved session or its project is gone)."""

    def __init__(self, message: str, permanent: bool = False):
        super().__init__(message)
        self.permanent = permanent


@dataclass(frozen=True)
class Project:
    id: str
    name: str
    repo_path: str
    agent: str = AGENT


def current_branch(repo_path: str) -> str | None:
    """Blocking. The checked-out branch, or None when it cannot be read or HEAD is detached."""
    import subprocess

    from proc_utils import no_window_kwargs

    try:
        out = subprocess.run(
            ["git", "-C", repo_path, "rev-parse", "--abbrev-ref", "HEAD"],
            capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=5, check=False,
            **no_window_kwargs(),
        ).stdout.strip()
    except (OSError, subprocess.SubprocessError):
        return None
    return out if out and out != "HEAD" else None


@dataclass(frozen=True)
class HostSession:
    pty_id: str
    vendor_session_id: str | None = None


@dataclass(frozen=True)
class RestoredSession:
    pty_id: str
    project: Project
    short: str
    vendor_session_id: str | None
    created_at: float


class SessionHost(Protocol):
    async def spawn(self, project: Project, labels: dict[str, str] | None = None) -> HostSession: ...
    async def restore(self, channel: str) -> list[RestoredSession]: ...
    async def deliver(self, pty_id: str, text: str) -> None: ...
    async def alive(self, pty_id: str) -> bool: ...
    async def sleeping(self, pty_id: str) -> bool: ...
    async def wake(self, pty_id: str, project: Project, labels: dict[str, str]) -> None: ...
    async def kill(self, pty_id: str) -> None: ...
    async def state(self, pty_id: str) -> dict | None: ...
    async def last_message(self, pty_id: str) -> str: ...
    async def output(self, pty_id: str, since: int) -> tuple[str, int]: ...


class LocalPtyHost:
    """Headless Claude Code sessions in this machine's PTY registry, pinned so neither the
    Code tab closing nor the idle-suspend sweep ends them."""

    async def spawn(self, project: Project, labels: dict[str, str] | None = None) -> HostSession:
        import generic_agent
        from fastapi import HTTPException
        from routes import generic_agent_routes

        req = generic_agent_routes.GenericAgentTerminalRequest(
            agent=project.agent, project_id=project.id, repo_path=project.repo_path, force_new=True
        )
        try:
            result = await generic_agent_routes.open_pinned_terminal(req, labels)
        except HTTPException as exc:
            raise HostError(f"Could not start {project.agent}: {exc.detail}") from exc
        pty_id = result["pty_session_id"]
        return HostSession(pty_id=pty_id, vendor_session_id=generic_agent.linked_session_id(pty_id))

    async def restore(self, channel: str) -> list[RestoredSession]:
        """The live remote sessions this channel started, read from the PTY host's labels.
        They outlive a backend restart; the labels carry what the backend forgot."""
        return await asyncio.to_thread(self._restore, channel)

    @staticmethod
    def _restore(channel: str) -> list[RestoredSession]:
        from routes import terminal
        from skills.code_agent.projects import get_project

        try:
            listed = terminal.host_sessions()
        except terminal.HostUnreachable as exc:
            raise HostError("The terminal host did not answer.") from exc
        found = []
        for entry in listed:
            meta = entry.get("meta") or {}
            if entry.get("done") or meta.get("remote_pinned") != "1" or meta.get("remote_channel") != channel:
                continue
            project = get_project(meta.get("project_id") or "")
            if not project or not project.get("repo_path") or not meta.get("remote_short"):
                _log.warning("remote session %s has no project or name to restore; left running", entry.get("id"))
                continue
            try:
                created = float(meta.get("remote_created") or 0)
            except ValueError:
                created = 0.0
            found.append(
                RestoredSession(
                    pty_id=entry["id"],
                    project=Project(
                        id=project["name"],
                        name=project["name"],
                        repo_path=project["repo_path"],
                        agent=meta.get("agent") or AGENT,
                    ),
                    short=meta["remote_short"],
                    vendor_session_id=meta.get("session_id"),
                    created_at=created,
                )
            )
        return found

    async def deliver(self, pty_id: str, text: str) -> None:
        """Types one message into a running session. The session's wake/suspend slot is held for
        the delivery, so the idle sweep cannot suspend it in the middle of the paste."""
        import agent_wake
        from routes import terminal

        session_id = ((await asyncio.to_thread(terminal.session_owner, pty_id)) or {}).get("session_id")
        if session_id and not agent_wake.claim(session_id):
            raise HostError("That session is being woken or suspended right now. Send it again in a moment.")
        try:
            await asyncio.to_thread(self._refuse_if_in_use, pty_id)
            await agent_wake._wait_ready(pty_id, agent_wake.LIVE_READY_SECONDS)
            await agent_wake._type_message(pty_id, agent_wake.clean(text))
        except agent_wake.WakeRefused as exc:
            raise HostError(exc.reason) from exc
        finally:
            if session_id:
                agent_wake.release(session_id)

    @staticmethod
    def _refuse_if_in_use(pty_id: str) -> None:
        """A message is never typed over someone who is using the session in AI Gator."""
        import agent_wake
        from routes import terminal

        entry = terminal.get_pty_session(pty_id)
        typing = entry is not None and time.time() - getattr(entry, "last_user_input", 0.0) < agent_wake.USER_TYPING_SECONDS
        if typing or terminal.has_viewer(pty_id, agent_wake.USER_TYPING_SECONDS):
            raise HostError(IN_USE_MESSAGE)

    async def alive(self, pty_id: str) -> bool:
        from routes import terminal

        return await asyncio.to_thread(terminal.is_pty_alive, pty_id)

    async def sleeping(self, pty_id: str) -> bool:
        """True when the idle sweep suspended this terminal and left its record: the session
        is saved and can be woken, but nothing is running."""
        import agent_suspend

        return await asyncio.to_thread(agent_suspend.suspended_record, pty_id) is not None

    async def wake(self, pty_id: str, project: Project, labels: dict[str, str]) -> None:
        """Resumes the saved session under its own terminal id and waits until it takes input.
        Returns only when the session is running and ready. Never starts a session of its own:
        every failure raises, and a session that is already open in another terminal is refused."""
        import agent_suspend
        import agent_wake

        record = await asyncio.to_thread(agent_suspend.suspended_record, pty_id)
        if record is None or not record.get("session_id"):
            raise HostError("That session was not saved, so it cannot be woken. Stop it and start a new one.", True)
        session_id = record["session_id"]
        if not agent_wake.claim(session_id):
            raise HostError("That session is being woken or suspended right now. Send it again in a moment.")
        try:
            await self._wake_claimed(pty_id, project, labels, record)
        finally:
            agent_wake.release(session_id)

    async def _wake_claimed(self, pty_id: str, project: Project, labels: dict[str, str], record: dict) -> None:
        import agent_sessions
        import agent_suspend
        import agent_wake
        from fastapi import HTTPException
        from routes import generic_agent_routes

        session_id, agent = record["session_id"], record.get("agent") or project.agent
        repo = await asyncio.to_thread(agent_wake._project_repo, record.get("project_id") or project.id)
        if not repo:
            raise HostError("The project this session belonged to no longer exists.", True)
        if await asyncio.to_thread(agent_sessions.find_session, repo, agent, session_id) is None:
            raise HostError("The saved session is gone, so it cannot be woken. Stop it and start a new one.", True)
        if await asyncio.to_thread(self._open_elsewhere, pty_id, agent, session_id):
            raise HostError(OPEN_ELSEWHERE_MESSAGE)
        req = generic_agent_routes.GenericAgentTerminalRequest(
            agent=agent, project_id=record.get("project_id") or project.id, repo_path=repo, resume_id=session_id
        )
        try:
            result = await generic_agent_routes.resume_suspended(req, pty_id, WOKEN_BY, "", labels)
        except HTTPException as exc:
            raise HostError(f"The session could not be woken: {exc.detail}") from exc
        except Exception as exc:
            _log.warning("could not wake %s", pty_id, exc_info=True)
            raise HostError("The session could not be woken.") from exc
        if result["pty_session_id"] != pty_id:
            raise HostError(OPEN_ELSEWHERE_MESSAGE)
        try:
            await self._wait_awake(pty_id)
        finally:
            # The record goes once the process holds the session. One that died on the way up
            # keeps it, so the next message can try again.
            running = await agent_wake._pty(pty_id)
            if running is not None and not running.done:
                await asyncio.to_thread(agent_suspend.forget, pty_id)

    @staticmethod
    def _open_elsewhere(pty_id: str, agent: str, session_id: str) -> bool:
        """True when a terminal other than this lane's holds the session: the user resumed it in
        the Code tab. Two processes must never share one stored session."""
        import generic_agent
        from routes import terminal

        for live_id, meta in terminal.live_pty_labels().items():
            if live_id != pty_id and meta.get("agent") == agent and meta.get("session_id") == session_id:
                return True
        for other in generic_agent.ptys_for_session(agent, session_id):
            entry = terminal.get_pty_session(other)
            if other != pty_id and entry is not None and not entry.done:
                return True
        return False

    async def _wait_awake(self, pty_id: str) -> None:
        """Waits for the resumed session to take input. A large old session makes Claude ask how to
        resume it (from a summary or in full) before it will take any: that is never answered
        for the user, so the session is closed again, still saved, and the user is told."""
        import agent_wake

        deadline = time.monotonic() + agent_wake.WAKE_READY_SECONDS
        while True:
            if await asyncio.to_thread(self._resume_prompt_showing, pty_id):
                await asyncio.to_thread(self._close_again, pty_id)
                raise HostError(RESUME_PROMPT_MESSAGE)
            try:
                await agent_wake._wait_ready(pty_id, min(PROMPT_CHECK_SECONDS, max(deadline - time.monotonic(), 0.1)))
                return
            except agent_wake.WakeRefused as exc:
                if exc.code != "not_ready" or time.monotonic() >= deadline:
                    raise HostError(exc.reason) from exc

    @staticmethod
    def _resume_prompt_showing(pty_id: str) -> bool:
        from routes import terminal

        entry = terminal.get_pty_session(pty_id)
        if entry is None:
            return False
        try:
            text, _ = entry.read_from(0)
        except Exception:
            return False
        return bool(RESUME_PROMPT.search(_ANSI.sub("", text)))

    @staticmethod
    def _close_again(pty_id: str) -> None:
        import generic_agent
        from routes import terminal

        if terminal.close_pty_session(pty_id):
            generic_agent.unpin_session(pty_id)

    async def kill(self, pty_id: str) -> None:
        import agent_suspend
        import generic_agent
        from routes import terminal

        # A sleeping lane has no process to close: stopping it only drops what was saved.
        if await asyncio.to_thread(terminal.is_pty_alive, pty_id):
            if not await asyncio.to_thread(terminal.close_pty_session, pty_id):
                raise HostError("The terminal could not be closed.")
        generic_agent.unpin_session(pty_id)
        await asyncio.to_thread(agent_suspend.forget, pty_id)

    async def state(self, pty_id: str) -> dict | None:
        import agent_state

        return (await asyncio.to_thread(agent_state.read_states, [pty_id])).get(pty_id)

    async def last_message(self, pty_id: str) -> str:
        return await asyncio.to_thread(self._last_message, pty_id)

    @staticmethod
    def _last_message(pty_id: str) -> str:
        import agent_handoff
        import agent_sessions
        from routes import terminal
        from skills.code_agent.projects import get_project

        meta = terminal.session_owner(pty_id) or {}
        repo = (get_project(meta.get("project_id") or "") or {}).get("repo_path")
        if not repo or not meta.get("session_id"):
            _log.warning("no project or vendor session id for %s; its reply cannot be read", pty_id)
            return ""
        text = ""
        for attempt in range(_TRANSCRIPT_TRIES):
            if attempt:
                time.sleep(_TRANSCRIPT_WAIT)
            try:
                rec = agent_sessions.find_session(repo, meta.get("agent") or AGENT, meta["session_id"])
                text = agent_sessions.last_assistant_text(rec) if rec else ""
            except Exception:
                _log.warning("could not read the transcript for %s", pty_id, exc_info=True)
                return ""
            if text:
                break
        if not text:
            _log.warning("the transcript of %s has no assistant reply yet", pty_id)
            return ""
        return agent_handoff.Redactor(agent_handoff._configured_api_keys())(text)

    async def output(self, pty_id: str, since: int) -> tuple[str, int]:
        from routes import terminal

        entry = await asyncio.to_thread(terminal.get_pty_session, pty_id)
        if entry is None:
            raise HostError("That session is no longer running.")
        text, end = entry.read_from(since)
        return _ANSI.sub("", text), end
