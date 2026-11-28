"""Turns channel messages into service calls and service events into channel replies.

Loop guards: Gator's own posts are ignored by the crocodile marker and by recorded post ids.
Each batch advances the stored last-processed id before anything runs, so a crash or restart
never runs a message twice."""

from __future__ import annotations

import asyncio
import dataclasses
import logging
import time
from dataclasses import dataclass
from typing import Callable

from remote import commands
from remote.channel import AutosendOff, Channel, InboundMessage
from remote.guard import Guard, limit
from remote.peers import Peer, PeerDirectory, PeerRefused, addressable, resolve as resolve_peer
from remote.service import ADOPTED, Event, RemoteError, RemoteService, Session
from remote.session_host import current_branch
from remote.state import State
from remote.window import ChatWindow
from teams_remote_control import _COMMAND_RE as LEGACY_CODE_RE

_log = logging.getLogger(__name__)

STALE_SECONDS = 15 * 60.0
AGENT_LABEL = "Claude"
WAITING_HEADLINE = commands.WAITING_HEADLINE
_TAGS = ("gator", AGENT_LABEL.lower())
_RESERVED_NAMES = frozenset((*commands.RESERVED, "all", *_TAGS))


class _Reply(RemoteError):
    """A RemoteError whose text is already a finished chat message."""


@dataclass
class _Turn:
    """One request being worked on. `acked` means the user has been told it is taking a while."""

    started: float
    last_note: float
    acked: bool = False


def _state_word(session: Session) -> str:
    if session.waiting:
        return commands.WAITING
    return commands.WORKING if session.awaiting_since is not None else commands.IDLE


class RemoteRunner:
    def __init__(
        self,
        channel: Channel,
        service: RemoteService,
        guard: Guard,
        state: State,
        clock: Callable[[], float] = time.time,
        stale_seconds: float | Callable[[], float] = STALE_SECONDS,
        first_prompt_hint: str = "",
        branch_of: Callable[[str], str | None] = current_branch,
        peers: PeerDirectory | None = None,
    ):
        self._channel = channel
        self._service = service
        self._guard = guard
        self._state = state
        self._clock = clock
        self._stale = stale_seconds
        self._hint = first_prompt_hint
        self._branch_of = branch_of
        self._peers = peers
        self._turns: dict[str, _Turn] = {}
        self._enabled = False
        self._timeout_noticed = False
        self._autosend_noticed = False
        self._window = ChatWindow(channel.name, state, clock)
        self._already_open = False
        self._not_sent_noticed: set[str] = set()
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
        """Its text is about opening a chat, so it is not said into one that is already open."""
        if not self._window.is_open():
            await self._post(commands.online())

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
            command = commands.parse(message.text) or await self._untagged(message)
            if command is None or not self._guard.armed:
                continue
            if message.created_at > 0 and self._clock() - message.created_at > limit(self._stale):
                skipped += 1
                continue
            if command.kind == "open":
                self._already_open = self._window.open(message.created_at)
                if not self._already_open:
                    self._not_sent_noticed.clear()
            elif command.kind not in ("stop_all", "bye"):
                self._window.extend()
            await self._run(command)
        if skipped:
            await self._post(commands.stale_skipped(skipped, limit(self._stale)))

    async def _untagged(self, message: InboundMessage) -> commands.Command | None:
        """An ordinary message inside the open window, routed like `@gator <text>`. Anything with no
        timestamp, that arrived before the window opened, or that the older `/code` relay owns, is not
        ours. A long message or one with an attachment is not sent to the agent: the self-chat is
        often a notepad, so pasted mail or logs must not become prompts."""
        if not self._window.is_open() or message.created_at <= 0 or message.created_at < self._window.opened_at():
            return None
        text = message.text.strip()
        if not text or LEGACY_CODE_RE.match(message.text):
            return None
        if message.attachments:
            await self._note_not_sent(message, "attachment", commands.attachment_not_sent)
            return None
        if len(text) > commands.UNTAGGED_MAX_CHARS:
            await self._note_not_sent(message, "too long", commands.too_long)
            return None
        command = commands.parse(f"@gator {text}")
        return dataclasses.replace(command, tagged=False) if command else None

    async def _note_not_sent(self, message: InboundMessage, reason: str, reply: Callable[[], str]) -> None:
        """One plain line per reason per window, however many messages are held back."""
        if reason in self._not_sent_noticed or not self._guard.armed:
            return
        if self._clock() - message.created_at > limit(self._stale):
            return
        self._not_sent_noticed.add(reason)
        await self._post(reply())

    async def _close_if_expired(self) -> None:
        if self._window.expired():
            self._window.close()
            await self._post(commands.chat_closed_quiet())

    def _is_own(self, message: InboundMessage) -> bool:
        return commands.is_own_message(message.text) or self._state.is_own_post(
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
        except _Reply as exc:
            await self._post(str(exc))
        except RemoteError as exc:
            await self._post(commands.error_reply(str(exc)))
        except Exception:
            _log.warning("Remote command %s failed", command.kind, exc_info=True)
            await self._post(commands.error_reply("That command failed and was not retried."))

    async def _dispatch(self, command: commands.Command) -> None:
        kind = command.kind
        if kind == "help":
            await self._post(commands.help_text(self._window.is_open()))
        elif kind == "open":
            await self._post(commands.already_open() if self._already_open else commands.greeting())
        elif kind == "bye":
            self._window.close()
            await self._post(commands.chat_closed_bye())
        elif kind == "list":
            await self._post(await self._list_text())
        elif kind == "status":
            await self._post(self._status(command.name))
        elif kind == "stop":
            await self._service.stop(self._pick(command.name, required=True)[0].id)
        elif kind == "stop_all":
            await self._stop_all()
        else:
            await self._send(command.text, command.tagged)

    async def _stop_all(self) -> None:
        stopped, failed = await self._service.stop_all()
        if failed:
            await self._post(
                commands.stop_all_failed(
                    ", ".join(s.short for s in failed), ", ".join(s.short for s in stopped)
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
                raise _Reply(commands.session_not_found(name))
            return [session]
        sessions = self._service.list()
        if required and len(sessions) != 1:
            if not sessions:
                raise _Reply(commands.no_sessions())
            raise _Reply(commands.which_to_stop([s.short for s in sessions]))
        return sessions

    def _reserved(self) -> frozenset[str]:
        return _RESERVED_NAMES | {s.short for s in self._service.list()}

    async def _peer_list(self, *, refresh: bool = False) -> list[Peer]:
        """The other agents in the default project that can be messaged. A listing that fails is no
        reason to refuse a command that is not about them."""
        if self._peers is None:
            return []
        try:
            project = self._service.default_project()
            if project is None:
                return []
            exclude = {s.pty_id for s in self._service.list()}
            return await self._peers.peers(project.id, exclude, refresh=refresh)
        except Exception as exc:
            _log.warning("Remote control could not list the other agents: %s", exc)
            return []

    async def _list_text(self) -> str:
        peers = await self._peer_list(refresh=True)
        reserved = self._reserved()
        names = [p.name.casefold() for p in peers]
        rows, reach = [], ""
        for peer in peers[: commands.PEERS_SHOWN]:
            by_name = addressable(peer, reserved) and names.count(peer.name.casefold()) == 1
            token = peer.name if by_name else peer.short
            reach = reach or token
            shown = commands.peer_label(peer.name) if by_name else f"{commands.peer_label(peer.name)} ({peer.short})"
            rows.append((shown, peer.state))
        return commands.session_list(
            [(s.short, s.project.name, _state_word(s)) for s in self._service.list()],
            rows,
            max(0, len(peers) - commands.PEERS_SHOWN),
            reach,
        )

    async def _try_peer(self, text: str, colon_only: bool = False) -> bool:
        """Sends `text` to the other agent its first words name. False when they name none."""
        peers = await self._peer_list()
        found = resolve_peer(peers, text, self._reserved(), colon_only) if peers else None
        if found is None:
            return False
        if found.peer is None:
            first = found.candidates[0]
            await self._audit_refusal(first.name, "ambiguous_name", "Several agents share that name.", text)
            raise _Reply(commands.peer_ambiguous(first.name, [(p.short, p.state) for p in found.candidates]))
        await self._message_peer(found.peer, found.text)
        return True

    async def _audit_refusal(self, peer_name: str, code: str, reason: str, text: str) -> None:
        import agent_wake

        sender = {"name": f"{self._channel.name.title()} chat"}
        try:
            await asyncio.to_thread(agent_wake.audit_refusal, sender, peer_name, code, reason, text)
        except Exception:
            _log.warning("could not audit a refused message to %s", peer_name, exc_info=True)

    async def _message_peer(self, peer: Peer, text: str) -> None:
        if not text:
            raise _Reply(commands.mention_needs_text(commands.peer_label(peer.name)))
        wait = self._peers.limiter.wait_seconds(peer.session_id)
        if wait:
            await self._audit_refusal(peer.name, "peer_limit", "The hourly limit for that agent was reached.", text)
            raise _Reply(commands.peer_limit(peer.name, self._peers.limiter.limit, wait))
        try:
            delivery = await self._peers.deliver(peer, text, f"{self._channel.name.title()} chat")
        except PeerRefused as exc:
            raise _Reply(commands.peer_refused(peer.name, exc.reason)) from exc
        project = self._service.default_project()
        if project is not None:
            try:
                self._service.adopt(delivery.pty_id, project, peer.name, peer.session_id)
            except RemoteError:
                _log.warning("could not watch %s for its reply; the message was delivered", peer.name)
        await self._post(commands.peer_sent(peer.name, delivery.woke))

    def _describe(self, sessions: list[Session]) -> str:
        return commands.session_list([(s.short, s.project.name, _state_word(s)) for s in sessions])

    def _status(self, name: str | None) -> str:
        sessions = self._pick(name)
        if len(sessions) != 1:
            return self._describe(sessions)
        s = sessions[0]
        since = s.awaiting_since if s.awaiting_since is not None else s.last_activity
        return commands.session_status(
            s.short, _state_word(s), since, s.last_activity, project=s.project.name, several=self._several(s)
        )

    async def _send(self, text: str, tagged: bool = True) -> None:
        """A message to a session. `@name text`, `name text` and `name: text` pick one; otherwise the
        waiting session if exactly one waits, else the only running one, else a new session in the
        default project. Another agent in the project is reached by its name, and only when the message
        carries the `@gator` tag: an open chat window never routes to one."""
        mention = commands.LEADING_MENTION_RE.match(text)
        if mention:
            name, rest = mention.group(1), (mention.group(2) or "").strip()
            session = self._service.resolve(name)
            if session is not None:
                if not rest:
                    raise _Reply(commands.mention_needs_text(session.short))
                await self._deliver(session, rest)
                return
            if name.lower() not in _TAGS:
                if tagged and await self._try_peer(text):
                    return
                recent = sorted(self._service.list(), key=lambda s: s.last_activity, reverse=True)
                raise _Reply(commands.unknown_mention(name, [s.short for s in recent]))
            if not rest:
                await self._post(commands.help_text(self._window.is_open()))
                return
            text = rest
        first, _, rest = text.partition(" ")
        named = self._service.resolve(first.rstrip(":"))
        if named is not None and rest.strip():
            await self._deliver(named, rest.strip())
            return
        sessions = self._service.list()
        waiting = [s for s in sessions if s.waiting]
        # A waiting session is being answered: the answer may start with a peer's name, so only
        # `name: text` reaches the peer then.
        if tagged and await self._try_peer(text, colon_only=bool(waiting)):
            return
        if len(waiting) == 1:
            await self._deliver(waiting[0], text)
        elif len(sessions) == 1:
            await self._deliver(sessions[0], text)
        elif sessions:
            raise _Reply(commands.which_session([s.short for s in sessions]))
        else:
            project = self._service.default_project()
            if project is None:
                raise RemoteError("No default project is set. Choose one in Settings, then resend.")
            prompt = f"{text}\n\n{self._hint}" if self._hint else text
            self._begin(await self._service.start(project, prompt))

    async def _deliver(self, session: Session, text: str) -> None:
        await self._service.send(session.id, text)
        self._begin(session)

    def _begin(self, session: Session) -> None:
        now = self._clock()
        self._turns[session.id] = _Turn(started=now, last_note=now)

    def _peer_ref(self, session: Session) -> str:
        """What to type to reach a watched agent: its name when a name picks it, else its id."""
        entry = {"session_id": session.vendor_session_id or "", "title": session.name}
        peer = Peer(entry)
        if peer.session_id and not addressable(peer, self._reserved()):
            return peer.short
        return commands.peer_label(session.name)

    async def _on_peer_event(self, event: Event) -> None:
        """What another agent answered to a message sent from chat, or that it closed before answering."""
        session = event.session
        project = session.project.name
        if event.kind in ("completed", "input-required"):
            waiting = event.kind == "input-required" or commands.asks_a_question(event.text)
            session.waiting = waiting
            ref = self._peer_ref(session)
            await self._post(commands.peer_result(session.name, project, event.text, waiting, ref))
        elif event.kind == "detached" and event.text:
            await self._post(commands.peer_exited(session.name, project))

    async def _on_event(self, event: Event) -> None:
        if event.session.kind == ADOPTED:
            await self._on_peer_event(event)
            return
        session = event.session
        short = session.short
        turn = self._turns.pop(session.id, None)
        several = self._several(session)
        project = session.project.name
        if event.kind in ("completed", "input-required"):
            waiting = event.kind == "input-required" or commands.asks_a_question(event.text)
            session.waiting = waiting
            if waiting:
                headline = WAITING_HEADLINE
            elif turn is None:
                headline = "Done."
            elif not turn.acked:
                headline = ""
            else:
                headline = commands.done_headline(self._clock() - turn.started)
            await self._post(
                commands.agent_result(AGENT_LABEL, short, headline, event.text, waiting, several, project=project)
            )
        elif event.kind == "failed":
            await self._post(commands.agent_exited(short, project=project, several=several))
        elif event.kind == "canceled":
            await self._post(commands.agent_stopped(short, project=project, several=several))
        else:
            await self._post(commands.working_ack(short, event.kind, project=project, several=several))

    def _several(self, session: Session) -> bool:
        """True while more than one session is live, counting one that has just left the table."""
        return len({s.id for s in self._service.list()} | {session.id}) > 1

    async def _report_progress(self) -> None:
        """A turn that outlives ACK_DELAY_SECONDS gets one 'Working on it', then 'Still working' every
        PROGRESS_SECONDS. A turn that finishes first never gets either, so a quick answer is one message."""
        now = self._clock()
        live = {s.id: s for s in self._service.list()}
        for session_id, turn in list(self._turns.items()):
            session = live.get(session_id)
            if session is None:
                self._turns.pop(session_id, None)
            elif not turn.acked and now - turn.started >= commands.ACK_DELAY_SECONDS:
                turn.acked, turn.last_note = True, now
                branch = await asyncio.to_thread(self._branch_of, session.project.repo_path)
                await self._post(
                    commands.working(session.short, branch, len(live) > 1, project=session.project.name)
                )
            elif turn.acked and now - turn.last_note >= commands.PROGRESS_SECONDS:
                turn.last_note = now
                await self._post(
                    commands.progress(
                        session.short, now - turn.started, project=session.project.name, several=len(live) > 1
                    )
                )

    async def tick(self) -> None:
        if self._guard.expired():
            self._guard.disarm()
            self._window.close()
            if not self._timeout_noticed:
                self._timeout_noticed = True
                await self._post(commands.timed_out(self._guard.armed_max_seconds))
        if self._guard.armed:
            await self._close_if_expired()
            await self._service.tick()
            await self._report_progress()
        else:
            # A message already sent to another agent still gets its answer after `stop all` or the
            # time limit; Remote's own sessions are gone by then, so only watched ones are checked.
            await self._service.tick(ADOPTED)
