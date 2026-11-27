"""Turns channel messages into service calls and service events into channel replies.

Loop guards: Gator's own posts are ignored by the SYSTEM_PREFIX and by recorded post ids.
Each batch advances the stored last-processed id before anything runs, so a crash or restart
never runs a message twice."""

from __future__ import annotations

import asyncio
import logging
import time
from typing import Callable

from remote import commands
from remote.channel import AutosendOff, Channel, InboundMessage
from remote.guard import Guard, limit
from remote.service import Event, RemoteError, RemoteService, Session
from remote.state import State
from remote.window import ChatWindow
from teams_remote_control import _COMMAND_RE as LEGACY_CODE_RE

_log = logging.getLogger(__name__)

STALE_SECONDS = 15 * 60.0
AGENT_LABEL = "Claude"
_HEADLINES = {
    "completed": "Done.",
    "input-required": "Waiting for your answer.",
    "failed": "The agent process exited. Send a message to start a new session.",
    "canceled": "Stopped.",
}


def _state_word(session: Session) -> str:
    if session.waiting:
        return "waiting for you"
    return "working" if session.awaiting_since is not None else "idle"


class RemoteRunner:
    def __init__(
        self,
        channel: Channel,
        service: RemoteService,
        guard: Guard,
        state: State,
        clock: Callable[[], float] = time.time,
        stale_seconds: float | Callable[[], float] = STALE_SECONDS,
    ):
        self._channel = channel
        self._service = service
        self._guard = guard
        self._state = state
        self._clock = clock
        self._stale = stale_seconds
        self._enabled = False
        self._timeout_noticed = False
        self._autosend_noticed = False
        self._window = ChatWindow(channel.name, state, clock)
        service.subscribe(self._on_event)

    def sync_enabled(self, enabled: bool) -> None:
        """Arms on the off-to-on edge only, so the cap stays in force until the switch is turned
        off and on again. `stop all` is stored, so it also holds across a backend restart."""
        channel = self._channel.name
        if enabled and not self._enabled:
            if not self._state.disarmed(channel):
                self._guard.arm()
            self._timeout_noticed = False
            self._autosend_noticed = False
        elif not enabled:
            if self._state.disarmed(channel):
                self._state.set_disarmed(channel, False)
            if self._enabled:
                self._guard.disarm()
            self._window.close()
        self._enabled = enabled

    async def restore(self) -> None:
        await self._service.restore()

    async def announce_online(self) -> None:
        await self._post(commands.system_reply("Online"))

    async def _post(self, text: str) -> None:
        try:
            await asyncio.to_thread(self._channel.post, text)
        except AutosendOff:
            if not self._autosend_noticed:
                self._autosend_noticed = True
                _log.info("Remote control is not replying on %s: auto-send is off", self._channel.name)
        except Exception as exc:
            _log.warning("Remote control could not post a reply: %s", exc)

    async def poll(self) -> None:
        await self.process(await asyncio.to_thread(self._channel.poll))

    async def process(self, messages: list[InboundMessage]) -> None:
        """`messages` is newest first, as the channel returns it."""
        channel = self._channel.name
        last = self._state.last_id(channel)
        if last is None:
            self._state.set_last_id(channel, messages[0].id if messages else "")
            return
        if not messages:
            return
        ids = [m.id for m in messages]
        fresh = messages[: ids.index(last)] if last in ids else messages
        self._state.set_last_id(channel, messages[0].id)
        skipped = 0
        for message in reversed(fresh):
            if self._is_own(message):
                continue
            await self._close_if_expired()
            command = commands.parse(message.text) or self._untagged(message)
            if command is None or not self._guard.armed:
                continue
            if self._clock() - message.created_at > limit(self._stale):
                skipped += 1
                continue
            if command.kind == "open":
                self._window.open(message.created_at)
            elif command.kind not in ("stop_all", "bye"):
                self._window.extend()
            await self._run(command)
        if skipped:
            await self._post(commands.stale_skipped(skipped, limit(self._stale)))

    def _untagged(self, message: InboundMessage) -> commands.Command | None:
        """An ordinary message inside the open window, routed like `@gator <text>`. Anything that
        arrived before the window opened, or that the older `/code` relay owns, is not ours."""
        if not self._window.is_open() or message.created_at < self._window.opened_at():
            return None
        if not message.text.strip() or LEGACY_CODE_RE.match(message.text):
            return None
        return commands.parse(f"@gator {message.text.strip()}")

    async def _close_if_expired(self) -> None:
        if self._window.expired():
            self._window.close()
            await self._post(commands.chat_closed_quiet())

    def _is_own(self, message: InboundMessage) -> bool:
        return message.text.lstrip().startswith(commands.SYSTEM_PREFIX) or self._state.is_own_post(
            self._channel.name, message.id
        )

    async def _run(self, command: commands.Command) -> None:
        stops = command.kind in ("stop", "stop_all")
        if not stops and not self._guard.allow_command():
            if self._guard.slow_down_due():
                await self._post(commands.slow_down(self._guard.wait_seconds()))
            return
        try:
            await self._dispatch(command)
        except RemoteError as exc:
            await self._post(commands.system_reply(str(exc)))
        except Exception:
            _log.warning("Remote command %s failed", command.kind, exc_info=True)
            await self._post(commands.system_reply("That command failed and was not retried."))

    async def _dispatch(self, command: commands.Command) -> None:
        kind = command.kind
        if kind == "help":
            await self._post(commands.help_text())
        elif kind == "open":
            await self._post(commands.greeting())
        elif kind == "bye":
            self._window.close()
            await self._post(commands.chat_closed_bye())
        elif kind == "list":
            await self._post(self._describe(self._service.list()))
        elif kind == "status":
            await self._post(self._describe(self._pick(command.name)))
        elif kind == "stop":
            await self._service.stop(self._pick(command.name, required=True)[0].id)
        elif kind == "stop_all":
            await self._stop_all()
        else:
            await self._send(command.text)

    async def _stop_all(self) -> None:
        stopped, failed = await self._service.stop_all()
        if failed:
            names = ", ".join(s.short for s in failed)
            done = f" Stopped: {', '.join(s.short for s in stopped)}." if stopped else ""
            await self._post(
                commands.system_reply(
                    f"Could not stop {names}; still running.{done} Remote control stays on. Send `@gator stop all` to try again."
                )
            )
            return
        self._guard.stop_all()
        self._state.set_disarmed(self._channel.name, True)
        self._window.close()
        await self._post(commands.stopped(len(stopped)) if stopped else commands.no_sessions())

    def _pick(self, name: str | None, required: bool = False) -> list[Session]:
        if name:
            session = self._service.resolve(name)
            if session is None:
                raise RemoteError(commands.not_found_text(name))
            return [session]
        sessions = self._service.list()
        if required and len(sessions) != 1:
            raise RemoteError(self._need_a_name(sessions))
        return sessions

    def _need_a_name(self, sessions: list[Session]) -> str:
        if not sessions:
            return "No remote sessions are running."
        return f"Which session? Name one: {', '.join(s.short for s in sessions)}."

    def _describe(self, sessions: list[Session]) -> str:
        return commands.session_list([(s.short, s.project.name, _state_word(s)) for s in sessions])

    async def _send(self, text: str) -> None:
        first, _, rest = text.partition(" ")
        named = self._service.resolve(first)
        if named is not None and rest.strip():
            await self._service.send(named.id, rest.strip())
            await self._ack(named, "Sent. Working on it.")
            return
        project = self._service.default_project()
        if project is None:
            raise RemoteError("No default project is set. Choose one in Settings, then resend.")
        sessions = [s for s in self._service.list() if s.project.id == project.id]
        if len(sessions) > 1:
            raise RemoteError(self._need_a_name(sessions) + " Start with the name, e.g. `@gator <name> <text>`.")
        if sessions:
            await self._service.send(sessions[0].id, text)
            await self._ack(sessions[0], "Sent. Working on it.")
            return
        session = await self._service.start(project, text)
        await self._ack(session, "Started. Working on it.")

    async def _ack(self, session: Session, text: str) -> None:
        await self._post(commands.agent_reply(AGENT_LABEL, session.short, text))

    async def _on_event(self, event: Event) -> None:
        headline = _HEADLINES.get(event.kind, event.kind)
        if event.kind in ("completed", "input-required"):
            await self._post(commands.agent_result(AGENT_LABEL, event.session.short, headline, event.text))
        else:
            await self._ack(event.session, headline)

    async def tick(self) -> None:
        if self._guard.expired():
            self._guard.disarm()
            self._window.close()
            if not self._timeout_noticed:
                self._timeout_noticed = True
                await self._post(commands.timed_out(self._guard.armed_max_seconds))
            return
        if self._guard.armed:
            await self._close_if_expired()
            await self._service.tick()
