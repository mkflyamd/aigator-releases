"""Background loop for Teams remote control: ticks sessions every few seconds, polls the
self-chat on a slower cadence. Gated on the existing `teams_remote_control_enabled` setting,
read fresh each cycle."""

from __future__ import annotations

import asyncio
import logging
import time
from typing import Callable

from config import load_config
from remote.guard import Guard
from remote.runner import RemoteRunner
from remote.service import RemoteService
from remote.session_host import LocalPtyHost, Project
from remote.state import State
from remote.teams_channel import TeamsSelfChat

_log = logging.getLogger(__name__)

STEP_SECONDS = 3.0
POLL_SECONDS = 10.0


def teams_switch_on() -> bool:
    return bool(load_config().get("teams_remote_control_enabled"))


def default_project() -> Project | None:
    from skills.code_agent import projects

    name = load_config().get("remote_default_project") or projects.get_active_project()
    meta = projects.get_project(name) if name else None
    if not meta or not meta.get("repo_path"):
        return None
    return Project(id=meta["name"], name=meta["name"], repo_path=meta["repo_path"])


class RemoteLoop:
    def __init__(
        self,
        runner: RemoteRunner,
        enabled: Callable[[], bool],
        clock: Callable[[], float] = time.time,
        poll_every: float = POLL_SECONDS,
    ):
        self._runner = runner
        self._enabled = enabled
        self._clock = clock
        self._poll_every = poll_every
        self._last_poll: float | None = None
        self._need_online = True
        self._poll_failing = False

    async def step(self) -> None:
        enabled = self._enabled()
        self._runner.sync_enabled(enabled)
        if not enabled:
            self._need_online = True
            self._last_poll = None
            return
        await self._runner.tick()
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
            self._need_online = True
            return
        self._poll_failing = False
        if self._need_online:
            self._need_online = False
            await self._runner.announce_online()


async def remote_control_loop() -> None:
    state = State()
    channel = TeamsSelfChat(state=state)
    guard = Guard()
    service = RemoteService(LocalPtyHost(), default_project=default_project)
    loop = RemoteLoop(RemoteRunner(channel, service, guard, state), teams_switch_on)
    while True:
        await asyncio.sleep(STEP_SECONDS)
        try:
            await loop.step()
        except Exception:
            _log.warning("Remote control step failed", exc_info=True)
