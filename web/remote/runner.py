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

from remote import commands, needs_you, prompts
from remote.bystanders import TerminalWatch
from remote.channel import AutosendOff, Channel, InboundMessage
from remote import master as master_window
from remote.guard import Guard, limit
from remote.peers import Peer, PeerDirectory, PeerRefused, addressable, resolve as resolve_peer
from remote.master import Master
from remote.service import (
    ADOPTED,
    LIVE,
    SLEEPING,
    STARTED,
    Aborted,
    Asleep,
    Elsewhere,
    Event,
    PromptGone,
    PromptRefused,
    Refusal,
    RemoteError,
    RemoteService,
    Session,
)
from remote.session_host import Project, current_branch
from remote.state import UNROUTED_PREFIX, State
from remote.window import ChatWindow
from teams_remote_control import _COMMAND_RE as LEGACY_CODE_RE

_log = logging.getLogger(__name__)

STALE_SECONDS = 15 * 60.0
AGENT_LABEL = "Claude"
WAITING_HEADLINE = commands.WAITING_HEADLINE
PROMPT_ROUTE_SECONDS = 12 * 3600.0
RETRY_POST_SECONDS = 60.0
PROMPT_HOLD_SECONDS = 2 * 3600.0
# Why an open terminal cannot be messaged at all, as opposed to not right now: the lane then starts afresh.
NOT_MESSAGEABLE = frozenset(("opted_out", "unsafe_mode", "unknown_mode", "switched_off", "admin_denied"))
# Refusals that a moment can mend; every other code stays until someone changes the other agent's setup.
TRANSIENT_REFUSALS = frozenset(("not_ready", "busy", "failed"))
_TAGS = ("gator", AGENT_LABEL.lower())
_RESERVED_NAMES = frozenset((*commands.RESERVED, "all", *_TAGS))


@dataclass
class _Turn:
    """One request being worked on. `acked` means the user has been told it is taking a while."""

    started: float
    last_note: float
    acked: bool = False


def _state_word(session: Session) -> str:
    if session.state in (commands.SLEEPING, commands.FAILED):
        return session.state
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
        master: Master | None = None,
        first_prompt_hint: str = "",
        branch_of: Callable[[str], str | None] = current_branch,
        peers: PeerDirectory | None = None,
        terminals: TerminalWatch | None = None,
    ):
        self._channel = channel
        self._service = service
        self._guard = guard
        self._state = state
        self._clock = clock
        self._stale = stale_seconds
        self._master = master or Master(state, clock)
        self._hint = first_prompt_hint
        self._branch_of = branch_of
        self._peers = peers
        self._terminals = terminals
        self._app: dict[str, Session] = {}
        self._answered: dict[str, float] = {}
        self._turns: dict[str, _Turn] = {}
        self._holds: dict[str, tuple[str, float]] = {}
        self._enabled = False
        self._stop_failure_logged: float | None = None
        self._autosend_noticed = False
        self._window = ChatWindow(channel.name, state, clock)
        self._already_open = False
        self._attachment_noticed = False
        self._summarized: set[tuple[str, str]] = set()
        self._unsent: dict[tuple[str, str], float] = {}
        self._unrecorded: set[tuple[str, str]] = set()
        self._wakes: set[asyncio.Task] = set()
        self._not_armed_noticed: object = None
        service.subscribe(self._on_event)

    def sync_enabled(self, enabled: bool) -> None:
        """The channel joins the shared window while its switch is on. `stop all` is stored, so it
        holds across a backend restart until the switch is turned off and on again."""
        channel = self._channel.name
        if enabled and not self._enabled:
            self._autosend_noticed = False
        elif not enabled:
            if self._state.disarmed(channel):
                self._state.set_disarmed(channel, False)
            self._window.close()
        self._enabled = enabled
        self._sync_guard()

    def _sync_guard(self) -> None:
        if self._enabled and self._master.active() and not self._state.disarmed(self._channel.name):
            self._guard.arm()
        else:
            self._guard.disarm()
            self._service.abort_wakes()

    @property
    def live(self) -> bool:
        """Armed now: the switch is on, the window is open, and `stop all` has not been sent."""
        return self._enabled and self._guard.armed and self._master.active()

    @property
    def window_open(self) -> bool:
        return self._master.active()

    async def restore(self) -> None:
        await self._service.restore()
        states = [s.state for s in self._service.list()]
        if self.live and (LIVE in states or SLEEPING in states):
            await self._post(commands.restarted(states.count(LIVE), states.count(SLEEPING)))

    def connection_failed(self, exc: Exception) -> None:
        """Remembers why the chat cannot be reached, for the Remote control pill and for the line said once it is back."""
        reason = " ".join(str(exc).split())[:120] or type(exc).__name__
        record = self._state.channel_value(self._channel.name, "connection") or {"since": self._clock()}
        self._state.set_channel_value(self._channel.name, "connection", {**record, "reason": reason})

    async def connection_recovered(self) -> None:
        record = self._state.channel_value(self._channel.name, "connection")
        if not record:
            return
        self._state.set_channel_value(self._channel.name, "connection", None)
        if self.live:
            await self._post(
                commands.reconnected(self._channel.name, self._clock() - record["since"], record["reason"])
            )

    async def shutdown(self) -> None:
        """Ends the background wakes before the backend goes down."""
        self._service.abort_wakes()
        tasks = list(self._wakes)
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)

    async def announce_online(self) -> None:
        """Its text is about opening a chat, so it is not said into one that is already open."""
        if not self._window.is_open():
            await self._post(commands.online())

    async def _post(self, text: str) -> str:
        """The id of the posted message, or "" when nothing was posted or the channel gave no id."""
        return await self._try_post(text) or ""

    async def _post_all(self, parts: list[str]) -> None:
        """The parts of one reply, in order."""
        for part in parts:
            await self._post(part)

    async def _try_post(self, text: str) -> str | None:
        """The id of the posted message ("" when the channel posted but gave no id), or None when it did not post."""
        try:
            return await asyncio.to_thread(self._channel.post, text) or ""
        except AutosendOff:
            if not self._autosend_noticed:
                self._autosend_noticed = True
                _log.info("Remote control is not replying on %s: auto-send is off", self._channel.name)
        except Exception as exc:
            _log.warning("Remote control could not post a reply: %s", exc)
        return None

    async def poll(self) -> None:
        await self.process(await asyncio.to_thread(self._channel.poll))
        await self.process_replies(await asyncio.to_thread(self._channel.poll_replies))

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
            command = self._reply_command(message) or commands.parse(message.text) or await self._untagged(message)
            if await self._execute(message, command):
                skipped += 1
        if skipped:
            await self._post(commands.stale_skipped(skipped, limit(self._stale)))

    async def process_replies(self, messages: list[InboundMessage]) -> None:
        """Replies the channel lists apart from its messages, newest first. Each one is read once."""
        skipped = 0
        for message in reversed(messages):
            if not self._is_own(message) and await self._execute(message, self._reply_command(message)):
                skipped += 1
        if skipped:
            await self._post(commands.stale_skipped(skipped, limit(self._stale)))

    async def _execute(self, message: InboundMessage, command: commands.Command | None) -> bool:
        """Runs `command` if it may run. True when it was dropped for being too old."""
        if command is None:
            return False
        if not self.live:
            await self._note_not_armed(message)
            return False
        if message.created_at > 0 and self._clock() - message.created_at > limit(self._stale):
            return True
        if command.kind == "open":
            self._already_open = self._window.open(message.created_at)
            if not self._already_open:
                self._attachment_noticed = False
        elif command.kind not in ("stop_all", "bye"):
            self._window.extend()
        await self._run(dataclasses.replace(command, sent_at=message.created_at))
        return False

    def _reply_command(self, message: InboundMessage) -> commands.Command | None:
        """A quote-reply or thread reply to a prompt message this chat posted answers that prompt, with the
        chat window closed and no `@gator`. An explicit command in it, such as `@gator stop`, still runs."""
        if not message.reply_to:
            return None
        if self._state.find_prompt_message(self._channel.name, message.reply_to, self._clock()) is None:
            return None
        typed = commands.parse(message.text)
        if typed is not None and typed.kind == "interrupt":
            return dataclasses.replace(typed, reply_to=message.reply_to)
        if typed is not None and typed.kind != "send":
            return typed
        text = typed.text if typed else message.text.strip()
        if text.lower().rstrip(".!") in commands.INTERRUPT_WORDS:
            return commands.Command("interrupt", reply_to=message.reply_to)
        return commands.Command("answer", text=text, reply_to=message.reply_to) if text else None

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
        mention = commands.LEADING_MENTION_RE.match(text)
        if mention and mention.group(1).lower() != "gator" and self._service.resolve(mention.group(1)) is None:
            return None
        if message.attachments:
            if not self._attachment_noticed and await self._note_not_sent(message, commands.attachment_not_sent):
                self._attachment_noticed = True
            return None
        if len(text) > commands.UNTAGGED_MAX_CHARS:
            await self._note_not_sent(message, commands.too_long)
            return None
        command = commands.parse(f"@gator {text}")
        return dataclasses.replace(command, tagged=False) if command else None

    async def _note_not_armed(self, message: InboundMessage) -> None:
        """A command that arrives while the switch is on but no window is open gets one plain line,
        and nothing runs: "timed out" when a window ran out, "not turned on" when none was opened
        (an upgrade, or after Disarm). Said once per window."""
        if not self._enabled or self._unhandled_deadline() is not None:
            return
        record = self._master.record()
        key = record["deadline"] if record else "never"
        if self._not_armed_noticed == key:
            return
        if message.created_at > 0 and self._clock() - message.created_at > limit(self._stale):
            return
        self._not_armed_noticed = key
        await self._post(commands.not_armed() if record is None else commands.timed_out_reply(master_window.ARM_SECONDS))

    async def _note_not_sent(self, message: InboundMessage, reply: Callable[[], str]) -> bool:
        if not self.live or self._clock() - message.created_at > limit(self._stale):
            return False
        await self._post(reply())
        return True

    def _anyone_waiting(self) -> bool:
        """True while some session shows a prompt or is working on a request, for at most PROMPT_HOLD_SECONDS
        each. A session that only sounds like it asked something has no prompt and does not keep the chat open."""
        now = self._clock()
        holds, held = {}, False
        for session in self._service.list():
            if session.prompt is not None:
                marker = session.prompt.id
            elif session.awaiting_since is not None and session.state == LIVE:
                marker = f"turn:{session.awaiting_since}"
            else:
                continue
            seen_id, since = self._holds.get(session.id, ("", now))
            since = since if seen_id == marker else now
            holds[session.id] = (marker, since)
            held = held or now - since < PROMPT_HOLD_SECONDS
        self._holds = holds
        return held

    async def _close_if_expired(self) -> None:
        if self._window.expired() and not self._anyone_waiting():
            self._window.close()
            await self._post(commands.chat_closed_quiet())

    def _is_own(self, message: InboundMessage) -> bool:
        return commands.is_own_message(message.text) or self._state.is_own_post(
            self._channel.name, message.id
        )

    async def _run(self, command: commands.Command) -> None:
        if not self._exempt_from_rate_limit(command) and not self._guard.allow_command():
            await self._post(commands.slow_down(self._guard.wait_seconds()))
            return
        try:
            await self._dispatch(command)
        except Refusal as exc:
            await self._post(str(exc))
        except RemoteError as exc:
            await self._post(commands.error_reply(str(exc)))
        except Exception:
            _log.warning("Remote command %s failed", command.kind, exc_info=True)
            await self._post(commands.command_failed())

    def _exempt_from_rate_limit(self, command: commands.Command) -> bool:
        """Stopping and answering a waiting prompt are never held back by the limit."""
        if command.kind in ("stop", "stop_all", "answer", "interrupt"):
            return True
        return command.kind == "send" and any(s.prompt is not None for s in self._service.list())

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
            await self._post(await self._status(command.name))
        elif kind == "stop":
            await self._service.stop(self._pick(command.name, required=True)[0].id)
        elif kind == "stop_all":
            await self._stop_all()
        elif kind == "answer":
            await self._answer_quoted(command)
        elif kind == "interrupt":
            await self._interrupt(command)
        else:
            await self._send(command.text, command.tagged, command.sent_at)

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
                raise Refusal(commands.session_not_found(name))
            return [session]
        sessions = self._service.list()
        if required and len(sessions) != 1:
            if not sessions:
                raise Refusal(commands.no_sessions())
            raise Refusal(commands.which_to_stop([s.short for s in sessions]))
        return sessions

    def _since(self, session: Session) -> float:
        if session.waiting:
            return session.last_event_at or session.last_activity
        turn = self._turns.get(session.id)
        if turn is not None and session.awaiting_since is not None:
            return turn.started
        return session.awaiting_since if session.awaiting_since is not None else session.last_activity

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
            self._session_rows(self._service.list()),
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
            raise Refusal(commands.peer_ambiguous(first.name, [(p.short, p.state) for p in found.candidates]))
        await self._message_peer(found.peer, found.text)
        return True

    async def _audit_refusal(self, peer_name: str, code: str, reason: str, text: str) -> None:
        import agent_wake

        sender = {"name": f"{self._channel.name.title()} chat"}
        try:
            await asyncio.to_thread(agent_wake.audit_refusal, sender, peer_name, code, reason, text)
        except Exception:
            _log.warning("could not audit a refused message to %s", peer_name, exc_info=True)

    async def _message_peer(self, peer: Peer, text: str, project: Project | None = None) -> None:
        if not text:
            raise Refusal(commands.mention_needs_text(commands.peer_label(peer.name)))
        wait = self._peers.limiter.wait_seconds(peer.session_id)
        if wait:
            await self._audit_refusal(peer.name, "peer_limit", "The hourly limit for that agent was reached.", text)
            raise Refusal(commands.peer_limit(peer.name, self._peers.limiter.limit, wait))
        try:
            delivery = await self._peers.deliver(peer, text, f"{self._channel.name.title()} chat")
        except PeerRefused as exc:
            raise Refusal(
                commands.peer_refused(peer.name, exc.reason, permanent=exc.code not in TRANSIENT_REFUSALS)
            ) from exc
        project = project or self._service.default_project()
        if project is not None:
            try:
                self._service.adopt(delivery.pty_id, project, peer.name, peer.session_id)
            except RemoteError:
                _log.warning("could not watch %s for its reply; the message was delivered", peer.name)
        await self._post(commands.peer_sent(peer.name, delivery.woke))

    def _session_rows(self, sessions: list[Session]) -> list[tuple[str, str, str, float, str]]:
        now = self._clock()
        return [
            (s.short, s.project.name, _state_word(s), now - self._since(s), prompts.answer_word(s.prompt))
            for s in sessions
        ]

    def _describe(self, sessions: list[Session]) -> str:
        return commands.session_list(self._session_rows(sessions))

    async def _status(self, name: str | None) -> str:
        sessions = self._pick(name)
        if len(sessions) != 1:
            return self._describe(sessions)
        s = sessions[0]
        if s.prompt is not None:
            return prompts.waiting_message(s.short, s.project.name, s.prompt)
        word = _state_word(s)
        return commands.session_status(
            s.short,
            word,
            self._since(s),
            s.last_activity,
            project=s.project.name,
            several=self._several(s),
            now=self._clock(),
            last_step=await self._service.last_step(s) if word == commands.WORKING else "",
        )

    async def _send(self, text: str, tagged: bool = True, sent_at: float = 0.0) -> None:
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
                    raise Refusal(commands.mention_needs_text(session.short))
                await self._deliver(session, rest, sent_at)
                return
            if name.lower() not in _TAGS:
                if tagged and await self._try_peer(text):
                    return
                recent = sorted(self._service.list(), key=lambda s: s.last_activity, reverse=True)
                raise Refusal(commands.unknown_mention(name, [s.short for s in recent]))
            if not rest:
                await self._post(commands.help_text(self._window.is_open()))
                return
            text = rest
        first, _, rest = text.partition(" ")
        named = self._service.resolve(first.rstrip(":"))
        if named is not None and rest.strip():
            await self._deliver(named, rest.strip(), sent_at)
            return
        sessions = self._service.list()
        waiting = [s for s in sessions if s.waiting]
        watched = self._watched_waiting()
        # A waiting session is being answered: the answer may start with a peer's name, so only
        # `name: text` reaches the peer then.
        if tagged and await self._try_peer(text, colon_only=bool(waiting or watched)):
            return
        if any(isinstance(prompts.resolve(s.prompt, text), prompts.Answer) for s in watched):
            if len(waiting) + len(watched) > 1:
                raise Refusal(commands.which_prompt())
            await self._answer(watched[0], text, sent_at)
            return
        if len(waiting) == 1:
            await self._deliver(waiting[0], text, sent_at)
        elif len(sessions) == 1:
            await self._deliver(sessions[0], text, sent_at)
        elif sessions:
            raise Refusal(commands.which_session([s.short for s in sessions]))
        else:
            project = self._service.default_project()
            if project is None:
                raise Refusal(commands.no_default_project())
            prompt = f"{text}\n\n{self._hint}" if self._hint else text
            self._begin(await self._service.start(project, prompt))

    async def _deliver(self, session: Session, text: str, sent_at: float = 0.0) -> None:
        if await self._service.needs_wake(session):
            if await self._route_elsewhere(session, text):
                return
            await self._start_wake(session, text)
            return
        await self._service.refresh(session.id)
        if session.waiting and session.prompt is not None:
            await self._answer(session, text, sent_at)
            return
        busy = session.awaiting_since is not None and session.kind == STARTED
        elapsed = self._clock() - self._since(session)
        try:
            await self._service.send(session.id, text)
        except Asleep:
            await self._start_wake(session, text)
            return
        except Refusal:
            raise
        except RemoteError as exc:
            raise Refusal(
                self._lane_copy(commands.send_failed, session, str(exc), permanent=exc.permanent)
            ) from exc
        self._state.clear_prompt_messages(self._channel.name, session.id)
        if not busy:
            self._begin(session)
            return
        self._turns.setdefault(session.id, _Turn(started=self._clock() - elapsed, last_note=self._clock()))
        await self._post(
            self._lane_copy(
                commands.busy_queued, session, elapsed, await self._service.last_step(session)
            )
        )

    async def _answer(self, session: Session, text: str, sent_at: float = 0.0, *, interrupt: bool = False) -> None:
        """A reply to a session that is showing a permission or a question: typed as that answer, or
        not typed at all, and said so. `interrupt` cancels the prompt with Escape instead."""
        short, project, prefix = session.short, session.project.name, self._prefix(session)
        try:
            result = await self._service.answer_session(session, text, sent_at, interrupt=interrupt, free_text=True)
        except PromptRefused as exc:
            raise Refusal(
                prompts.waiting_message(short, project, exc.prompt, refused=exc.reason, prefix=prefix)
            ) from exc
        except PromptGone as exc:
            self._state.clear_prompt_messages(self._channel.name, session.id)
            raise Refusal(prompts.confirmation(short, project, prompts.ALREADY_ANSWERED, prefix=prefix)) from exc
        self._state.clear_prompt_messages(self._channel.name, session.id)
        if session.id in self._app:
            self._answered[session.pty_id] = session.last_event_at
        elif not result.ends_turn and session.kind != ADOPTED:
            self._begin(session)
        await self._post(prompts.confirmation(short, project, result.done, prefix=prefix))
        await self._notify_waiting()

    async def _answer_quoted(self, command: commands.Command) -> None:
        """The reply to one prompt message goes to that message's session, and only while that prompt is the
        one the session is showing. Otherwise nothing is typed and the user is told it was already answered."""
        await self._answer(self._quoted_session(command), command.text)

    async def _interrupt(self, command: commands.Command) -> None:
        """`esc`: cancels the prompt a session is showing and keeps the session. A quote-reply names its prompt;
        otherwise the one waiting session, or the one named."""
        if command.reply_to:
            await self._answer(self._quoted_session(command), "", interrupt=True)
            return
        waiting = [
            s
            for s in [*self._service.list(), *self._service.watched(ADOPTED), *self._app.values()]
            if s.waiting and s.prompt is not None
        ]
        if command.name:
            waiting = [s for s in waiting if command.name in (s.short.lower(), s.name.lower())]
        if not waiting:
            raise Refusal(commands.nothing_to_cancel())
        if len(waiting) > 1:
            raise Refusal(commands.which_to_cancel([s.short for s in waiting]))
        await self._answer(waiting[0], "", command.sent_at, interrupt=True)

    def _quoted_session(self, command: commands.Command) -> Session:
        found = self._state.find_prompt_message(self._channel.name, command.reply_to or "", self._clock())
        record, is_open = found if found else ({}, False)
        session = self._tracked(record.get("session_id", ""))
        if session is None:
            raise Refusal(commands.system_reply(prompts.ALREADY_ANSWERED, []))
        shown = session.prompt
        if not (is_open and session.waiting and shown is not None and shown.id == record["prompt_id"]):
            raise Refusal(
                prompts.confirmation(
                    session.short, session.project.name, prompts.ALREADY_ANSWERED, prefix=self._prefix(session)
                )
            )
        return session

    def _prefix(self, session: Session) -> str:
        """The label of a prompt message: Remote's own sessions use the default, another agent its name, a
        terminal Remote did not start its project."""
        if session.id in self._app:
            return commands.agent_prefix(session.project.name)
        if session.kind == ADOPTED:
            return commands.peer_prefix(session.name, session.project.name)
        return ""

    def _tracked(self, session_id: str) -> Session | None:
        """A session whose prompts can reach chat: one Remote started, one it watches, or a waiting terminal."""
        return (
            self._app.get(session_id)
            or next((s for s in self._service.list() if s.id == session_id), None)
            or next((s for s in self._service.watched(ADOPTED) if s.id == session_id), None)
        )

    def _watched_waiting(self) -> list[Session]:
        """Sessions Remote did not start that wait on a prompt chat can answer."""
        return [
            s
            for s in [*self._service.watched(ADOPTED), *self._app.values()]
            if s.waiting and s.prompt is not None and s.prompt.answerable
        ]

    async def _post_prompt(self, session: Session, prompt: prompts.Prompt) -> bool:
        """One message for this session, remembered by its message id with the prompt and an expiry. A session
        started outside chat says how long it has waited."""
        now = self._clock()
        waited = None if session.from_chat else now - self._since(session)
        text = prompts.waiting_message(
            session.short, session.project.name, prompt, waited=waited, prefix=self._prefix(session)
        )
        message_id = await self._try_post(text)
        if message_id is None:
            return False
        # Posted but the channel gave no id: remember it as sent so it is never posted twice; no reply can route to it.
        route_id = message_id or f"{UNROUTED_PREFIX}{prompt.id}"
        try:
            self._state.record_prompt_message(
                self._channel.name, route_id, session.id, prompt.id, now + PROMPT_ROUTE_SECONDS, now
            )
        except Exception as exc:
            # The message is out; a record that could not be saved must not make the next tick post it again.
            _log.warning("Remote control could not save the record of a prompt message: %s", exc)
            self._unrecorded.add((session.id, prompt.id))
        return True

    async def _scan_terminals(self) -> None:
        """The AI Gator terminals that Remote did not start and that are waiting, as sessions kept apart from
        the service's. Their prompt is read like any other and answered through the same guards; Remote never
        starts, wakes or closes one."""
        if self._terminals is None:
            return
        try:
            skip = {s.pty_id for s in [*self._service.list(), *self._service.watched(ADOPTED)]}
            seen = await asyncio.to_thread(self._terminals.waiting, skip)
        except Exception as exc:
            _log.warning("Remote control could not look at the terminals: %s", exc)
            return
        found: dict[str, Session] = {}
        for item in seen:
            if item.state_at <= self._answered.get(item.pty_id, float("-inf")):
                continue
            session_id = f"app:{item.pty_id}"
            found[session_id] = self._app.get(session_id) or Session(
                id=session_id,
                pty_id=item.pty_id,
                project=item.project,
                short=item.project.name,
                vendor_session_id=None,
                created_at=item.prompt.at,
                last_activity=item.prompt.at,
                from_chat=False,
                kind=ADOPTED,
            )
            session = found[session_id]
            if session.prompt is None or session.prompt.id != item.prompt.id:
                session.prompt, session.waiting = item.prompt, True
                session.prompt_seen_at = self._clock()
                session.last_event_at, session.last_activity = item.state_at, item.prompt.at
        self._app = found

    async def _notify_waiting(self) -> None:
        """Posts a message for each waiting session that is due one and has a place, and names the rest once."""
        sessions = [*self._service.list(), *self._service.watched(ADOPTED), *self._app.values()]
        showing = {(s.id, s.prompt.id) for s in sessions if s.waiting and s.prompt is not None}
        for record in self._state.prompt_messages(self._channel.name):
            if (record["session_id"], record["prompt_id"]) not in showing:
                self._state.clear_prompt_messages(self._channel.name, record["session_id"])
        self._unrecorded &= showing
        posted = {(m["session_id"], m["prompt_id"]) for m in self._state.prompt_messages(self._channel.name)}
        posted |= self._unrecorded
        now = self._clock()
        self._unsent = {k: at for k, at in self._unsent.items() if k in showing and now - at < RETRY_POST_SECONDS}
        due = needs_you.plan(
            [s for s in sessions if (s.id, s.prompt.id if s.prompt else "") not in self._unsent],
            posted,
            self._since,
            now,
        )
        for session in due.send:
            if not await self._post_prompt(session, session.prompt):
                self._unsent[(session.id, session.prompt.id)] = now
        rest = {(s.id, s.prompt.id) for s in due.rest}
        if rest - self._summarized:
            now = self._clock()
            await self._post(prompts.more_waiting([(s.short, now - self._since(s)) for s in due.rest]))
        self._summarized = rest

    async def _route_elsewhere(self, session: Session, text: str) -> bool:
        """A lane whose saved session is open in another terminal is never woken, so the message goes where the
        session is: typed into that terminal the way a message to any other agent is (only when it is idle,
        never woken, closed or suspended from here). When that terminal cannot be messaged at all, the stale
        lane is dropped and a new session takes the message. True when the message was dealt with."""
        other = await self._service.open_elsewhere(session)
        if other is None:
            return False
        try:
            peer = await self._peers.by_pty(other) if self._peers is not None else None
        except Exception as exc:
            _log.warning("Remote control could not look up the terminal that holds %s: %s", session.short, exc)
            peer = None
        if peer is not None:
            try:
                await self._message_peer(peer, text, session.project)
                return True
            except Refusal as exc:
                cause = exc.__cause__
                if not (isinstance(cause, PeerRefused) and cause.code in NOT_MESSAGEABLE):
                    raise
        await self._service.replace_lane(session)
        prompt = f"{text}\n\n{self._hint}" if self._hint else text
        fresh = await self._service.start(session.project, prompt)
        self._begin(fresh)
        await self._post(self._lane_copy(commands.lane_moved_on, fresh))
        return True

    async def _start_wake(self, session: Session, text: str) -> None:
        """Answers at once and wakes in the background: a wake takes seconds, and the polling loop
        must keep running. begin_wake refuses a second wake of the same lane and one too soon after
        a failure, so a burst of messages cannot start more than one."""
        if session.waking:
            session.queued.append(text)
            await self._post(self._lane_copy(commands.still_waking, session))
            return
        self._service.begin_wake(session)
        await self._post(self._lane_copy(commands.waking, session))
        task = asyncio.create_task(self._wake(session, text))
        self._service.attach_wake(session, task)
        self._wakes.add(task)
        task.add_done_callback(self._wakes.discard)

    async def _wake(self, session: Session, text: str) -> None:
        try:
            await self._service.wake(session, text, proceed=lambda: self._guard.armed)
        except Aborted:
            return
        except Elsewhere:
            await self._after_elsewhere(session, text)
        except RemoteError as exc:
            if session.stopping:
                return
            await self._post(self._lane_copy(commands.wake_failed, session, str(exc), permanent=exc.permanent))
        except Exception:
            _log.warning("Remote wake of %s failed", session.short, exc_info=True)
            if session.stopping:
                return
            await self._post(self._lane_copy(commands.wake_failed, session))
        else:
            self._begin(session)
            await self._send_queued(session)
        finally:
            session.queued.clear()

    async def _send_queued(self, session: Session) -> None:
        """Messages that arrived while the lane was waking follow the one that woke it, in order."""
        for text in list(session.queued):
            try:
                await self._service.send(session.id, text)
            except RemoteError as exc:
                await self._post(self._lane_copy(commands.send_failed, session, str(exc), permanent=exc.permanent))
                return

    async def _after_elsewhere(self, session: Session, text: str) -> None:
        """The session was opened in another terminal while it was waking: the same routing as before the wake."""
        if session.stopping:
            return
        try:
            if await self._route_elsewhere(session, text):
                return
        except Refusal as exc:
            await self._post(str(exc))
            return
        except RemoteError as exc:
            await self._post(self._lane_copy(commands.send_failed, session, str(exc), permanent=exc.permanent))
            return
        await self._post(self._lane_copy(commands.wake_failed, session, "The session changed while it was waking."))

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
        keep = session.prompt.id if event.kind == "input-required" and session.prompt is not None else ""
        self._state.clear_prompt_messages(self._channel.name, session.id, keep)
        if event.kind == "input-required":
            if self.live:
                await self._notify_waiting()
        elif event.kind == "completed":
            waiting = commands.asks_a_question(event.text)
            session.waiting = waiting
            ref = self._peer_ref(session)
            await self._post_all(commands.peer_result(session.name, project, event.text, waiting, ref))
        elif event.kind == "detached" and event.text:
            await self._post(commands.peer_exited(session.name, project))

    async def _on_event(self, event: Event) -> None:
        if event.session.kind == ADOPTED:
            await self._on_peer_event(event)
            return
        session = event.session
        turn = self._turns.pop(session.id, None)
        if not self.live:
            return
        short = session.short
        several = self._several(session)
        project = session.project.name
        keep = session.prompt.id if event.kind == "input-required" and session.prompt is not None else ""
        self._state.clear_prompt_messages(self._channel.name, session.id, keep)
        if event.kind in ("completed", "input-required"):
            self._window.extend()
        if event.kind == "input-required" and session.prompt is not None:
            await self._notify_waiting()
        elif event.kind in ("completed", "input-required"):
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
            await self._post_all(
                commands.agent_result(AGENT_LABEL, short, headline, event.text, waiting, several, project=project)
            )
        elif event.kind == "failed":
            await self._post(commands.agent_exited(short, project=project, several=several))
        elif event.kind == "canceled":
            await self._post(commands.agent_stopped(short, project=project, several=several))
        elif event.kind == "lost":
            await self._post(commands.lane_lost(short, project=project, several=several))
        elif event.kind == "replaced":
            await self._post(commands.lane_replaced(short, project=project, several=several))
        elif event.kind == "duplicate":
            await self._post(commands.duplicate_lane(short, project=project, several=several))
        else:
            await self._post(commands.working_ack(short, event.kind, project=project, several=several))

    def _lane_copy(self, build, session: Session, *args, **kwargs) -> str:
        return build(session.short, *args, project=session.project.name, several=self._several(session), **kwargs)

    def _several(self, session: Session) -> bool:
        return self._service.several(session)

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
                        session.short,
                        now - turn.started,
                        await self._service.last_step(session),
                        project=session.project.name,
                        several=len(live) > 1,
                    )
                )

    async def tick(self) -> None:
        self._sync_guard()
        if self._master.active():
            self._not_armed_noticed = None
        if self._master.expired():
            await self._expire()
        elif self.live:
            await self._warn_if_due()
        if self.live:
            if self._anyone_waiting():
                self._window.hold()
            await self._close_if_expired()
        await self._service.tick()
        if self.live:
            await self._report_progress()
            await self._scan_terminals()
            await self._notify_waiting()
        else:
            self._app = {}

    @property
    def deadline_pending(self) -> bool:
        """The window has closed and this channel's sessions have not been stopped for it yet."""
        return self._unhandled_deadline() is not None

    def _unhandled_deadline(self) -> float | None:
        record = self._master.record()
        if record is None or not self._master.expired():
            return None
        if self._state.channel_value(self._channel.name, "expiry_handled") == record["deadline"]:
            return None
        return record["deadline"]

    async def _stop_at_deadline(self) -> bool:
        """Stops every session the way `stop all` does. A session that will not stop is retried on
        the next tick, so the caller only goes on once none are left. True when the stop
        finished for a window that is still closed."""
        deadline = self._unhandled_deadline()
        if deadline is None:
            return False
        stopped, failed = await self._service.stop_all()
        if failed:
            if self._stop_failure_logged != deadline:
                self._stop_failure_logged = deadline
                _log.warning("Remote control expired but %s would not stop; retrying", ", ".join(s.short for s in failed))
            return False
        self._state.set_channel_value(self._channel.name, "expiry_handled", deadline)
        if self._master.active():
            return False
        self._guard.stop_all()
        self._window.close()
        return True

    async def stop_after_deadline(self) -> None:
        """A channel whose switch is off still stops its sessions at the deadline, and says nothing."""
        await self._stop_at_deadline()

    async def _expire(self) -> None:
        if await self._stop_at_deadline():
            await self._post(commands.timed_out(master_window.ARM_SECONDS))

    async def _warn_if_due(self) -> None:
        record = self._master.record()
        if record is None:
            return
        deadline = record["deadline"]
        channel = self._channel.name
        if self._master.remaining() > master_window.WARN_SECONDS:
            return
        if self._state.channel_value(channel, "warned") == deadline:
            return
        self._state.set_channel_value(channel, "warned", deadline)
        await self._post(commands.turns_off_soon(master_window.WARN_SECONDS))
