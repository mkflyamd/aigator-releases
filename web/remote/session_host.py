"""Where remote sessions run. The service calls this interface only, so a server-hosted
tier or the cross-agent relay's terminal adapter can wrap or replace LocalPtyHost."""

from __future__ import annotations

import asyncio
import logging
import re
from dataclasses import dataclass
from typing import Protocol

_log = logging.getLogger(__name__)

AGENT = "claude"
_ANSI = re.compile(r"\x1b\[[0-?]*[ -/]*[@-~]|\x1b\][^\x07\x1b]*(?:\x07|\x1b\\)|\x1b[@-_]")


class HostError(Exception):
    """The host could not do what was asked; the message is for the user."""


@dataclass(frozen=True)
class Project:
    id: str
    name: str
    repo_path: str
    agent: str = AGENT


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
        except terminal.pty_client.HostError as exc:
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
        import agent_wake

        try:
            await agent_wake._wait_ready(pty_id, agent_wake.LIVE_READY_SECONDS)
            await agent_wake._type_message(pty_id, agent_wake.clean(text))
        except agent_wake.WakeRefused as exc:
            raise HostError(exc.reason) from exc

    async def alive(self, pty_id: str) -> bool:
        from routes import terminal

        return await asyncio.to_thread(terminal.is_pty_alive, pty_id)

    async def kill(self, pty_id: str) -> None:
        import generic_agent
        from routes import terminal

        if not await asyncio.to_thread(terminal.close_pty_session, pty_id):
            raise HostError("The terminal could not be closed.")
        generic_agent.unpin_session(pty_id)

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
            return ""
        try:
            rec = agent_sessions.find_session(repo, meta.get("agent") or AGENT, meta["session_id"])
            pairs = agent_sessions._transcript_messages(rec) if rec else []
        except Exception:
            _log.warning("could not read the transcript for %s", pty_id, exc_info=True)
            return ""
        text = next((t for role, t in reversed(pairs) if role == "assistant"), "")
        return agent_handoff.Redactor(agent_handoff._configured_api_keys())(text)

    async def output(self, pty_id: str, since: int) -> tuple[str, int]:
        from routes import terminal

        entry = await asyncio.to_thread(terminal.get_pty_session, pty_id)
        if entry is None:
            raise HostError("That session is no longer running.")
        text, end = entry.read_from(since)
        return _ANSI.sub("", text), end
