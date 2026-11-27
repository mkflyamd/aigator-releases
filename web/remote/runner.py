"""Turns channel messages into service calls and service events into channel replies.

Loop guards: Gator's own posts are ignored by the "[Gator" prefix and by recorded post ids.
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

_log = logging.getLogger(__name__)

STALE_SECONDS = 15 * 60.0
AGENT_LABEL = "Claude"
HELP = (
    "Commands: `@gator <text>` runs it in your Claude session. `@gator <name> <text>` picks a session. "
    "`@gator list`, `@gator status [name]`, `@gator stop [name]`, `@gator stop all`, `@gator help`."
)
_EVENT_TEXT = {
    "completed": "Done.",
    "input-required": "Waiting for your answer.",
    "failed": "The agent process exited.",
    "canceled": "Stopped.",
}


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
            command = commands.parse(message.text)
            if command is None or not self._guard.armed:
                continue
            if self._clock() - message.created_at > limit(self._stale):
                skipped += 1
                continue
            await self._run(command)
        if skipped:
            await self._post(
                commands.system_reply(f"Skipped {skipped} message(s) received while I was offline. Resend if still needed.")
            )

    def _is_own(self, message: InboundMessage) -> bool:
        return message.text.lstrip().startswith(commands.SYSTEM_PREFIX) or self._state.is_own_post(
            self._channel.name, message.id
        )

    async def _run(self, command: commands.Command) -> None:
        stops = command.kind in ("stop", "stop_all")
        if not stops and not self._guard.allow_command():
            if self._guard.slow_down_due():
                await self._post(commands.system_reply("Slow down: too many commands in the last 10 minutes. This one was dropped."))
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
            await self._post(commands.system_reply(HELP))
        elif kind == "list":
            await self._post(commands.system_reply(self._describe(self._service.list())))
        elif kind == "status":
            sessions = self._pick(command.name)
            await self._post(commands.system_reply(self._describe(sessions)))
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
        names = f" ({', '.join(s.short for s in stopped)})" if stopped else ""
        count = f"Stopped {len(stopped)} remote session(s){names}." if stopped else "No remote sessions were running."
        await self._post(commands.system_reply(f"{count} Remote control is off until you re-arm it in Settings."))

    def _pick(self, name: str | None, required: bool = False) -> list[Session]:
        if name:
            session = self._service.resolve(name)
            if session is None:
                raise RemoteError(f"No session named {name}. Send `@gator list` to see the running ones.")
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
        if not sessions:
            return "No remote sessions are running."
        return "Sessions:\n" + "\n".join(
            f"- {s.short} ({AGENT_LABEL}, {s.project.name}) {'working' if s.awaiting_since is not None else 'idle'}"
            for s in sessions
        )

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
        text = event.text.strip() or _EVENT_TEXT.get(event.kind, event.kind)
        await self._ack(event.session, text)

    async def tick(self) -> None:
        if self._guard.expired():
            self._guard.disarm()
            if not self._timeout_noticed:
                self._timeout_noticed = True
                await self._post(commands.system_reply("Remote control timed out. Re-arm it in Settings."))
            return
        if self._guard.armed:
            await self._service.tick()
