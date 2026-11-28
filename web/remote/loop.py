"""Background loop for remote control: ticks sessions every few seconds, polls each channel's
self-chat on a slower cadence. Teams and Slack run side by side, each with its own state,
guard, session list and switch (`teams_remote_control_enabled`, `slack_remote_control_enabled`),
read fresh each cycle."""

from __future__ import annotations

import asyncio
import logging
import time
from typing import Callable

from config import load_config
from remote import commands, settings
from remote.bystanders import LocalTerminalWatch
from remote.guard import Guard
from remote.peers import PeerDirectory, WakeGateway
from remote.master import Master
from remote.owner import ChannelOwner
from remote.runner import RemoteRunner
from remote.service import RemoteError, RemoteService
from remote.session_host import LocalPtyHost, Project
from remote.slack_channel import SlackSelfDM
from remote.state import State, shared
from remote.teams_channel import TeamsSelfChat

_log = logging.getLogger(__name__)

STEP_SECONDS = 3.0
POLL_SECONDS = 10.0


def teams_switch_on() -> bool:
    return bool(load_config().get("teams_remote_control_enabled"))


def slack_switch_on() -> bool:
    return bool(load_config().get("slack_remote_control_enabled"))


def default_project() -> Project | None:
    """The Settings project, else the active one. A Settings project that no longer exists is
    refused outright; it never falls back to another project."""
    from skills.code_agent import projects

    chosen = load_config().get(settings.DEFAULT_PROJECT_KEY)
    name = chosen or projects.get_active_project()
    meta = projects.get_project(name) if name else None
    if not meta or not meta.get("repo_path"):
        if chosen:
            raise RemoteError(f'The default project "{chosen}" no longer exists. Choose another in Settings, then resend.')
        return None
    return Project(id=meta["name"], name=meta["name"], repo_path=meta["repo_path"])


class RemoteLoop:
    def __init__(
        self,
        runner: RemoteRunner,
        enabled: Callable[[], bool],
        clock: Callable[[], float] = time.time,
        poll_every: float = POLL_SECONDS,
        owner: ChannelOwner | None = None,
    ):
        self._runner = runner
        self._owner = owner
        self._enabled = enabled
        self._clock = clock
        self._poll_every = poll_every
        self._last_poll: float | None = None
        self._need_online = True
        self._poll_failing = False
        self._was_live = False
        self._restored = False
        self._restore_failing = False

    async def _restore(self) -> bool:
        """After a backend restart the sessions are still running in the PTY host. Commands wait
        until they are known, or a plain message would start a second agent next to a live one."""
        if self._restored:
            return True
        try:
            await self._runner.restore()
        except RemoteError as exc:
            if not self._restore_failing:
                _log.warning("Remote control could not restore its sessions yet: %s", exc)
            self._restore_failing = True
            return False
        self._restore_failing = False
        self._restored = True
        return True

    async def shutdown(self) -> None:
        await self._runner.shutdown()

    async def step(self) -> None:
        enabled = self._enabled()
        if enabled and self._owner is not None and not self._owner.acquire():
            return
        self._runner.sync_enabled(enabled)
        if not enabled:
            if self._owner is not None and not self._runner.deadline_pending:
                self._owner.release()
            if not self._runner.window_open:
                self._was_live = False
            self._last_poll = None
            if self._runner.deadline_pending and await self._restore():
                await self._runner.stop_after_deadline()
            return
        if not await self._restore():
            return
        await self._runner.tick()
        live = self._runner.live
        if live and not self._was_live:
            self._need_online = True
        self._was_live = live
        now = self._clock()
        if self._last_poll is not None and now - self._last_poll < self._poll_every:
            return
        self._last_poll = now
        try:
            await self._runner.poll()
        except Exception as exc:
            if not self._poll_failing:
                _log.warning("Remote control poll failed: %s", exc)
            self._poll_failing = True
            return
        self._poll_failing = False
        if self._need_online and live:
            self._need_online = False
            await self._runner.announce_online()


def _build_loop(channel, state: State, enabled: Callable[[], bool]) -> RemoteLoop:
    service = RemoteService(
        LocalPtyHost(channel.name),
        default_project=default_project,
        idle_seconds=settings.idle_seconds,
        channel=channel.name,
        state=state,
    )
    runner = RemoteRunner(
        channel,
        service,
        Guard(),
        state,
        stale_seconds=settings.stale_seconds,
        master=Master(state),
        first_prompt_hint=commands.BREVITY_HINT,
        peers=PeerDirectory(WakeGateway(), settings.peer_messages_per_hour),
        terminals=LocalTerminalWatch(),
    )
    return RemoteLoop(runner, enabled, owner=ChannelOwner(channel.name))


def build_loops(state: State | None = None) -> list[RemoteLoop]:
    state = state or shared()
    return [
        _build_loop(TeamsSelfChat(state=state), state, teams_switch_on),
        _build_loop(SlackSelfDM(state=state), state, slack_switch_on),
    ]


async def _run_channel(loop: RemoteLoop) -> None:
    """One task per channel: a command that waits on its agent holds only its own channel."""
    try:
        while True:
            await asyncio.sleep(STEP_SECONDS)
            try:
                await loop.step()
            except Exception:
                _log.warning("Remote control step failed", exc_info=True)
    finally:
        await asyncio.shield(loop.shutdown())


async def remote_control_loop() -> None:
    await asyncio.gather(*(_run_channel(loop) for loop in build_loops()))
