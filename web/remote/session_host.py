"""Where remote sessions run. The service calls this interface only, so a server-hosted
tier or the cross-agent relay's terminal adapter can wrap or replace LocalPtyHost."""

from __future__ import annotations

import asyncio
import logging
import re
import time
from dataclasses import dataclass
from typing import TYPE_CHECKING, Callable, Protocol

import pty_client

if TYPE_CHECKING:
    from remote.prompts import Prompt

_log = logging.getLogger(__name__)

AGENT = "claude"
_TRANSCRIPT_TRIES = 4
_STEP_RECORDS: dict[tuple[str, str, str], dict] = {}
_TRANSCRIPT_WAIT = 0.5
SCREEN_TAIL_CHARS = 12000
_ANSI = re.compile(r"\x1b\[[0-?]*[ -/]*[@-~]|\x1b\][^\x07\x1b]*(?:\x07|\x1b\\)|\x1b[@-_]")
WOKEN_BY = "Remote control"
PROMPT_CHECK_SECONDS = 3.0
PROMPT_TAIL_CHARS = 2000
TYPE_SETTLE_SECONDS = 0.5
# Claude Code asks this before resuming a large old session. Only the dialog's own shape counts: its
# two numbered choices on consecutive lines, each at the start of a line (a selection marker or a
# box edge may precede it). The same words in prose, or in a quoted transcript, do not match.
_CHOICE = r"^[ \t│|]*(?:[>❯›]\s*)?\d\.\s+"
RESUME_PROMPT = re.compile(
    _CHOICE + r"Resume from summary[^\n]*\n(?:[ \t│|]*\r?\n)*" + _CHOICE + r"Resume full session as-is",
    re.MULTILINE,
)
IN_USE_MESSAGE = "Someone is using that session in AI Gator right now, so nothing was sent. Send it again when they are done."
OPEN_ELSEWHERE_MESSAGE = (
    "That session is open in another terminal on this computer, so it was not woken. "
    "Close it there, or keep using it there."
)
HOST_UNREACHABLE_MESSAGE = "The terminal host did not answer, so nothing was done. Try again in a moment."
WAKE_CANCELLED_MESSAGE = "The wake was called off."
RESUME_PROMPT_MESSAGE = (
    "Claude is asking how to resume this large session (from a summary or in full), "
    "and it will not take a message until someone answers. Nothing was sent. "
    "Resume it once from the Code tab in AI Gator and choose there."
)


async def _finish_even_if_cancelled(coro) -> None:
    """The paste and the Enter that follows are one step: a cancel between them would leave the text half typed
    in the session's input."""
    task = asyncio.ensure_future(coro)
    try:
        await asyncio.shield(task)
    except asyncio.CancelledError:
        await asyncio.wait({task})
        if not task.cancelled():
            task.exception()
        raise


class HostError(Exception):
    """The host could not do what was asked; the message is for the user. `permanent` means
    trying again cannot help (the saved session or its project is gone)."""

    def __init__(self, message: str, permanent: bool = False):
        super().__init__(message)
        self.permanent = permanent


class StalePrompt(HostError):
    """The prompt being answered is gone or has changed, so nothing was typed."""


def read_prompt(pty_id: str, redact=None) -> Prompt | None:
    """What the agent in this terminal is asking, from the hook file it wrote, redacted and capped. None when
    it wrote none. Everything that shows or answers a prompt reads it here, so the ids always agree."""
    import agent_handoff
    import agent_state
    from remote import prompts

    found = agent_state.read_prompt(pty_id)
    if not found:
        return None
    redact = redact or agent_handoff.Redactor(agent_handoff._configured_api_keys())
    parsed = prompts.parse(found["payload"], found["at"], redact) if found["payload"] is not None else None
    return parsed or prompts.unreadable(found["at"])


class Declined(HostError):
    """The caller's `proceed` said no just before the text would have been typed."""


class NoTypedAnswer(HostError):
    """The question is still showing but its screen has no row that takes typed words, so nothing was typed."""


class OpenElsewhere(HostError):
    """The lane's saved session is running in another terminal, so it is never woken a second time."""


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
    async def deliver(self, pty_id: str, text: str, proceed: Callable[[], bool] | None = None) -> None: ...
    async def alive(self, pty_id: str) -> bool: ...
    async def sleeping(self, pty_id: str) -> bool: ...
    async def saved(self, project: Project, vendor_session_id: str | None) -> bool: ...
    async def open_elsewhere(self, pty_id: str, project: Project, vendor_session_id: str | None) -> str | None: ...
    async def wake(
        self,
        pty_id: str,
        project: Project,
        labels: dict[str, str],
        vendor_session_id: str | None = None,
        cancelled: Callable[[], bool] = lambda: False,
    ) -> None: ...
    async def kill(self, pty_id: str) -> None: ...
    async def state(self, pty_id: str) -> dict | None: ...
    async def last_message(self, pty_id: str) -> str: ...
    async def last_step(self, pty_id: str) -> str: ...
    async def output(self, pty_id: str, since: int) -> tuple[str, int]: ...
    async def prompt(self, pty_id: str) -> Prompt | None: ...
    async def answer(self, pty_id: str, prompt_id: str, keys: tuple[str, ...], ends_turn: bool = False) -> None: ...


class LocalPtyHost:
    """Headless Claude Code sessions in this machine's PTY registry, pinned so neither the
    Code tab closing nor the idle-suspend sweep ends them."""

    def __init__(self, channel: str | None = None):
        self._channel = channel

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
        except pty_client.HostError as exc:
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

    async def deliver(self, pty_id: str, text: str, proceed: Callable[[], bool] | None = None) -> None:
        """Types one message into a running session. The session's wake/suspend slot is held for
        the delivery, so the idle sweep cannot suspend it in the middle of the paste. `proceed` is asked at the
        moment of typing, after the wait for the session to take input, and a no types nothing."""
        import agent_wake
        from routes import terminal

        session_id = ((await asyncio.to_thread(terminal.session_owner, pty_id)) or {}).get("session_id")
        if session_id and not agent_wake.claim(session_id):
            raise HostError("That session is being woken or suspended right now. Send it again in a moment.")
        try:
            await asyncio.to_thread(self._refuse_if_in_use, pty_id)
            await agent_wake._wait_ready(pty_id, agent_wake.LIVE_READY_SECONDS)
            # The wait can be long: someone may have opened the terminal meanwhile.
            await asyncio.sleep(TYPE_SETTLE_SECONDS)
            await asyncio.to_thread(self._refuse_if_in_use, pty_id)
            if proceed is not None and not proceed():
                raise Declined("Remote control turned off before the message was typed.")
            await _finish_even_if_cancelled(agent_wake._type_message(pty_id, agent_wake.clean(text)))
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
        """Asks the terminal host and never guesses: a host that does not answer raises HostError,
        so "could not ask" is never taken for "not running"."""
        from routes import terminal

        try:
            return await asyncio.to_thread(terminal.pty_alive_strict, pty_id)
        except pty_client.HostError as exc:
            raise HostError(HOST_UNREACHABLE_MESSAGE) from exc

    async def sleeping(self, pty_id: str) -> bool:
        """True when the idle sweep suspended this terminal and left its record: the session
        is saved and can be woken, but nothing is running."""
        import agent_suspend

        return await asyncio.to_thread(agent_suspend.suspended_record, pty_id) is not None

    async def saved(self, project: Project, vendor_session_id: str | None) -> bool:
        """True when the agent's own stored session for this lane is on disk, so the lane can be
        woken even though nothing records it as suspended."""
        import agent_sessions
        import agent_wake

        if not vendor_session_id:
            return False
        repo = await asyncio.to_thread(agent_wake._project_repo, project.id)
        if not repo:
            return False
        try:
            found = await asyncio.to_thread(agent_sessions.find_session, repo, project.agent, vendor_session_id)
        except Exception:
            _log.warning("could not look up the stored session %s", vendor_session_id, exc_info=True)
            return False
        return found is not None

    async def open_elsewhere(self, pty_id: str, project: Project, vendor_session_id: str | None) -> str | None:
        """The terminal other than this lane's that is running the lane's saved session, or None. A host
        that does not answer raises HostError: "could not ask" is never taken for "nobody has it"."""
        import agent_suspend

        record = await asyncio.to_thread(agent_suspend.suspended_record, pty_id) or {}
        session_id = record.get("session_id") or vendor_session_id
        if not session_id:
            return None
        try:
            return await asyncio.to_thread(self._open_elsewhere, pty_id, record.get("agent") or project.agent, session_id)
        except pty_client.HostError as exc:
            raise HostError(HOST_UNREACHABLE_MESSAGE) from exc

    async def wake(
        self,
        pty_id: str,
        project: Project,
        labels: dict[str, str],
        vendor_session_id: str | None = None,
        cancelled: Callable[[], bool] = lambda: False,
    ) -> None:
        """Resumes the lane's session under its own terminal id and waits until it takes input.
        Returns only when the session is running and ready, and at once when it already is. The
        session comes from the suspend record, or from the lane when the record is gone. Never
        starts a session of its own: every failure raises, a session open in another terminal is
        refused, and one that fails on the way up is closed again and stays saved. `cancelled` is
        polled while waiting, so a stop is not held up by a slow wake."""
        import agent_suspend
        import agent_wake

        if await self.alive(pty_id):
            return
        record = await asyncio.to_thread(agent_suspend.suspended_record, pty_id) or {}
        session_id = record.get("session_id") or vendor_session_id
        if not session_id:
            raise HostError("That session was not saved, so it cannot be woken. Stop it and start a new one.", True)
        if not agent_wake.claim(session_id):
            raise HostError("That session is being woken or suspended right now. Send it again in a moment.")
        try:
            await self._wake_claimed(
                pty_id,
                labels,
                session_id,
                record.get("agent") or project.agent,
                record.get("project_id") or project.id,
                cancelled,
            )
        finally:
            agent_wake.release(session_id)

    async def _wake_claimed(
        self,
        pty_id: str,
        labels: dict[str, str],
        session_id: str,
        agent: str,
        project_id: str,
        cancelled: Callable[[], bool],
    ) -> None:
        import agent_sessions
        import agent_suspend
        import agent_wake
        from fastapi import HTTPException
        from routes import generic_agent_routes, terminal

        repo = await asyncio.to_thread(agent_wake._project_repo, project_id)
        if not repo:
            raise HostError("The project this session belonged to no longer exists.", True)
        if await asyncio.to_thread(agent_sessions.find_session, repo, agent, session_id) is None:
            raise HostError("The saved session is gone, so it cannot be woken. Stop it and start a new one.", True)

        async def guard() -> None:
            # Runs under the resume lock, so what it checks cannot change before the spawn.
            try:
                elsewhere = await asyncio.to_thread(self._open_elsewhere, pty_id, agent, session_id)
            except pty_client.HostError as exc:
                raise HostError(HOST_UNREACHABLE_MESSAGE) from exc
            if elsewhere:
                raise OpenElsewhere(OPEN_ELSEWHERE_MESSAGE, True)
            if cancelled():
                raise HostError(WAKE_CANCELLED_MESSAGE)

        req = generic_agent_routes.GenericAgentTerminalRequest(
            agent=agent, project_id=project_id, repo_path=repo, resume_id=session_id
        )
        try:
            result = await generic_agent_routes.resume_suspended(req, pty_id, WOKEN_BY, "", labels, guard)
        except HostError:
            raise
        except HTTPException as exc:
            raise HostError(f"The session could not be woken: {exc.detail}") from exc
        except Exception as exc:
            _log.warning("could not wake %s", pty_id, exc_info=True)
            await asyncio.to_thread(self._close_again, pty_id)
            raise HostError("The session could not be woken.") from exc
        if result["pty_session_id"] != pty_id:
            raise OpenElsewhere(OPEN_ELSEWHERE_MESSAGE, True)
        try:
            await self._wait_awake(pty_id, cancelled)
        except BaseException:
            # Whatever went wrong once the process had started, it is closed again and its record
            # kept: the session stays asleep and the next message can try once more.
            await asyncio.to_thread(self._close_again, pty_id)
            raise
        await asyncio.to_thread(agent_suspend.forget, pty_id)

    @staticmethod
    def _open_elsewhere(pty_id: str, agent: str, session_id: str) -> str | None:
        """The terminal other than this lane's that holds the session: the user resumed it in the
        Code tab. Two processes must never share one stored session. Raises pty_client.HostError
        when the terminal host cannot be asked."""
        import generic_agent
        from routes import terminal

        for live_id, meta in terminal.live_pty_labels(strict=True).items():
            if live_id != pty_id and meta.get("agent") == agent and meta.get("session_id") == session_id:
                return live_id
        for other in generic_agent.ptys_for_session(agent, session_id):
            entry = terminal.get_pty_session(other)
            if other != pty_id and entry is not None and not entry.done:
                return other
        return None

    async def _wait_awake(self, pty_id: str, cancelled: Callable[[], bool] = lambda: False) -> None:
        """Waits for the resumed session to take input. A large old session makes Claude ask how to
        resume it (from a summary or in full) before it will take any: that is never answered
        for the user, so the caller closes it again, still saved, and the user is told."""
        import agent_wake

        deadline = time.monotonic() + agent_wake.WAKE_READY_SECONDS
        while True:
            if cancelled():
                raise HostError(WAKE_CANCELLED_MESSAGE)
            if await asyncio.to_thread(self._resume_prompt_showing, pty_id):
                raise HostError(RESUME_PROMPT_MESSAGE)
            try:
                await agent_wake._wait_ready(pty_id, min(PROMPT_CHECK_SECONDS, max(deadline - time.monotonic(), 0.1)))
                return
            except agent_wake.WakeRefused as exc:
                if exc.code != "not_ready" or time.monotonic() >= deadline:
                    raise HostError(exc.reason) from exc

    @staticmethod
    def _resume_prompt_showing(pty_id: str) -> bool:
        """Only the end of the screen counts: the dialog is what the terminal shows now, and the
        same words further back may be the agent quoting its own transcript."""
        from routes import terminal

        entry = terminal.get_pty_session(pty_id)
        if entry is None:
            return False
        try:
            text, _ = entry.read_from(0)
        except Exception:
            return False
        return bool(RESUME_PROMPT.search(_ANSI.sub("", text)[-PROMPT_TAIL_CHARS:]))

    @staticmethod
    def _close_again(pty_id: str) -> None:
        import generic_agent
        from routes import terminal

        if terminal.close_pty_session(pty_id):
            generic_agent.unpin_session(pty_id)
        else:
            _log.warning("could not close %s again after a failed wake", pty_id)

    async def kill(self, pty_id: str) -> None:
        import agent_suspend
        import generic_agent
        from routes import terminal

        # A sleeping lane has no process to close: stopping it only drops what was saved.
        if await self.alive(pty_id):
            # Another agent's terminal is never Remote control's to close, whatever id it is handed.
            meta = await asyncio.to_thread(terminal.session_owner, pty_id) or {}
            if self._channel is None or meta.get("remote_pinned") != "1" or meta.get("remote_channel") != self._channel:
                raise HostError("That session was not started by Remote control, so it was left running.")
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

    async def last_step(self, pty_id: str) -> str:
        return await asyncio.to_thread(self._last_step, pty_id)

    @staticmethod
    def _last_step(pty_id: str) -> str:
        import agent_sessions
        from routes import terminal
        from skills.code_agent.projects import get_project

        meta = terminal.session_owner(pty_id) or {}
        repo = (get_project(meta.get("project_id") or "") or {}).get("repo_path")
        if not repo or not meta.get("session_id"):
            return ""
        key = (repo, meta.get("agent") or AGENT, meta["session_id"])
        try:
            rec = _STEP_RECORDS.get(key)
            if rec is None:
                rec = agent_sessions.find_session(*key)
                if rec:
                    if len(_STEP_RECORDS) >= 64:
                        _STEP_RECORDS.clear()
                    _STEP_RECORDS[key] = rec
            return agent_sessions.last_step(rec) if rec else ""
        except Exception:
            _STEP_RECORDS.pop(key, None)
            _log.warning("could not read the last step of %s", pty_id, exc_info=True)
            return ""

    async def output(self, pty_id: str, since: int) -> tuple[str, int]:
        from routes import terminal

        entry = await asyncio.to_thread(terminal.get_pty_session, pty_id)
        if entry is None:
            raise HostError("That session is no longer running.")
        text, end = entry.read_from(since)
        return _ANSI.sub("", text), end

    async def prompt(self, pty_id: str) -> Prompt | None:
        return await asyncio.to_thread(self._prompt, pty_id)

    @staticmethod
    def _prompt(pty_id: str) -> Prompt | None:
        return read_prompt(pty_id)

    async def answer(self, pty_id: str, prompt_id: str, keys: tuple[str, ...], ends_turn: bool = False) -> None:
        """Types `keys` only while the agent is still showing the prompt `prompt_id`. No hook fires when the
        prompt is answered at the terminal, so the prompt file and the asking state outlive it; the terminal
        itself is checked: no keys typed there since the prompt appeared, and (for a permission) its dialog
        still the last thing on screen. A turn that the keys end fires no hook, so idle is reported here."""
        import agent_state
        from remote import prompts
        from routes import terminal

        shown = await self.prompt(pty_id)
        state = await self.state(pty_id)
        if shown is None or shown.id != prompt_id or not state or state["state"] != "asking":
            raise StalePrompt("That prompt is no longer showing.")
        entry = await asyncio.to_thread(terminal.get_pty_session, pty_id)
        if entry is None:
            raise HostError("That session is no longer running.")
        if entry.last_user_input > shown.at:
            raise StalePrompt("It was answered at the terminal.")
        typed = shown.kind == prompts.QUESTION and prompts.types_text(keys)
        if shown.kind == prompts.PERMISSION or keys == (prompts.ESCAPE,) or typed:
            _, end = entry.read_from(10**12)
            tail, _ = entry.read_from(max(0, end - SCREEN_TAIL_CHARS))
            tail = _ANSI.sub("", tail)
            if shown.kind == prompts.PERMISSION:
                if not prompts.permission_dialog_showing(tail, shown):
                    raise StalePrompt("The terminal is no longer showing that permission.")
            elif not prompts.escape_footer_showing(tail):
                raise StalePrompt("The terminal is no longer showing that question.")
            elif typed and not prompts.other_row_showing(tail, len(shown.choices)):
                raise NoTypedAnswer("The terminal's question has no row for typed words.")
        for index, key in enumerate(keys):
            if index:
                await asyncio.sleep(prompts.KEY_PAUSE_SECONDS)
            if not await asyncio.to_thread(terminal.write_pty_session, pty_id, key):
                raise HostError("The answer could not be typed into the terminal.")
        await asyncio.to_thread(agent_state.clear_prompt, pty_id)
        if ends_turn:
            await asyncio.to_thread(agent_state.set_state, pty_id, "idle")
