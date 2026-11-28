"""Turns channel messages into service calls and service events into channel replies.

Loop guards: Gator's own posts are ignored by the crocodile marker and by recorded post ids.
Each batch advances the stored last-processed id before anything runs, so a crash or restart
never runs a message twice."""

from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass
from typing import Callable

from remote import commands, needs_you, prompts
from remote.channel import AutosendOff, Channel, InboundMessage
from remote import master as master_window
from remote.guard import Guard, limit
from remote.master import Master
from remote.service import Event, PromptGone, PromptRefused, RemoteError, RemoteService, Session
from remote.session_host import current_branch
from remote.state import State
from remote.window import ChatWindow
from teams_remote_control import _COMMAND_RE as LEGACY_CODE_RE

_log = logging.getLogger(__name__)

STALE_SECONDS = 15 * 60.0
AGENT_LABEL = "Claude"
WAITING_HEADLINE = "Waiting for your answer."
PROMPT_ROUTE_SECONDS = 12 * 3600.0
RETRY_POST_SECONDS = 60.0
UNROUTED_PREFIX = "unrouted:"
PROMPT_HOLD_SECONDS = 2 * 3600.0
_TAGS = ("gator", AGENT_LABEL.lower())


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
        master: Master | None = None,
        first_prompt_hint: str = "",
        branch_of: Callable[[str], str | None] = current_branch,
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
        self._turns: dict[str, _Turn] = {}
        self._holds: dict[str, tuple[str, float]] = {}
        self._enabled = False
        self._stop_failure_logged: float | None = None
        self._autosend_noticed = False
        self._window = ChatWindow(channel.name, state, clock)
        self._already_open = False
        self._not_sent_noticed: set[str] = set()
        self._summarized: set[tuple[str, str]] = set()
        self._unsent: dict[tuple[str, str], float] = {}
        self._not_armed_noticed = False
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

    @property
    def live(self) -> bool:
        """Armed now: the switch is on, the window is open, and `stop all` has not been sent."""
        return self._enabled and self._guard.armed and self._master.active()

    @property
    def window_open(self) -> bool:
        return self._master.active()

    async def restore(self) -> None:
        await self._service.restore()

    async def announce_online(self) -> None:
        """Its text is about opening a chat, so it is not said into one that is already open."""
        if not self._window.is_open():
            await self._post(commands.online())

    async def _post(self, text: str) -> str:
        """The id of the posted message, or "" when nothing was posted or the channel gave no id."""
        return await self._try_post(text) or ""

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
                self._not_sent_noticed.clear()
        elif command.kind not in ("stop_all", "bye"):
            self._window.extend()
        await self._run(command)
        return False

    def _reply_command(self, message: InboundMessage) -> commands.Command | None:
        """A quote-reply or thread reply to a prompt message this chat posted answers that prompt, with the
        chat window closed and no `@gator`. An explicit command in it, such as `@gator stop`, still runs."""
        if not message.reply_to:
            return None
        if self._state.find_prompt_message(self._channel.name, message.reply_to, self._clock()) is None:
            return None
        typed = commands.parse(message.text)
        if typed is not None and typed.kind != "send":
            return typed
        text = typed.text if typed else message.text.strip()
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
        if message.attachments:
            await self._note_not_sent(message, "attachment", commands.attachment_not_sent)
            return None
        if len(text) > commands.UNTAGGED_MAX_CHARS:
            await self._note_not_sent(message, "too long", commands.too_long)
            return None
        return commands.parse(f"@gator {text}")

    async def _note_not_armed(self, message: InboundMessage) -> None:
        """A switch that is on with no window ever opened (an upgrade, or after Disarm) gets one
        plain line, and nothing runs. After a window has run out the channel stays silent."""
        if self._not_armed_noticed or not self._enabled or self._master.record() is not None:
            return
        if message.created_at > 0 and self._clock() - message.created_at > limit(self._stale):
            return
        self._not_armed_noticed = True
        await self._post(commands.not_armed())

    async def _note_not_sent(self, message: InboundMessage, reason: str, reply: Callable[[], str]) -> None:
        """One plain line per reason per window, however many messages are held back."""
        if reason in self._not_sent_noticed or not self.live:
            return
        if self._clock() - message.created_at > limit(self._stale):
            return
        self._not_sent_noticed.add(reason)
        await self._post(reply())

    def _anyone_waiting(self) -> bool:
        """True while some session shows a prompt, for at most PROMPT_HOLD_SECONDS each. A session that only
        sounds like it asked something has no prompt and does not keep the chat open."""
        now = self._clock()
        holds, held = {}, False
        for session in self._service.list():
            if session.prompt is None:
                continue
            seen_id, since = self._holds.get(session.id, ("", now))
            since = since if seen_id == session.prompt.id else now
            holds[session.id] = (session.prompt.id, since)
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
            await self._post(self._describe(self._service.list()))
        elif kind == "status":
            await self._post(self._status(command.name))
        elif kind == "stop":
            await self._service.stop(self._pick(command.name, required=True)[0].id)
        elif kind == "stop_all":
            await self._stop_all()
        elif kind == "answer":
            await self._answer_quoted(command)
        else:
            await self._send(command.text)

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

    def _since(self, session: Session) -> float:
        if session.waiting:
            return session.last_event_at or session.last_activity
        return session.awaiting_since if session.awaiting_since is not None else session.last_activity

    def _describe(self, sessions: list[Session]) -> str:
        now = self._clock()
        return commands.session_list(
            [
                (s.short, s.project.name, _state_word(s), now - self._since(s), prompts.answer_word(s.prompt))
                for s in sessions
            ]
        )

    def _status(self, name: str | None) -> str:
        sessions = self._pick(name)
        if len(sessions) != 1:
            return self._describe(sessions)
        s = sessions[0]
        return commands.session_status(
            s.short, _state_word(s), self._since(s), s.last_activity, project=s.project.name, several=self._several(s)
        )

    async def _send(self, text: str) -> None:
        """A message to a session. `@name text`, `name text` and `name: text` pick one; otherwise the
        waiting session if exactly one waits, else the only running one, else a new session in the
        default project."""
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
        if session.waiting and session.prompt is not None:
            await self._answer(session, text)
            return
        await self._service.send(session.id, text)
        self._state.clear_prompt_messages(self._channel.name, session.id)
        self._begin(session)

    async def _answer(self, session: Session, text: str) -> None:
        """A reply to a session that is showing a permission or a question: typed as that answer, or
        not typed at all, and said so."""
        short, project = session.short, session.project.name
        try:
            result = await self._service.answer(session.id, text)
        except PromptRefused as exc:
            raise _Reply(prompts.waiting_message(short, project, exc.prompt, refused=exc.reason)) from exc
        except PromptGone as exc:
            self._state.clear_prompt_messages(self._channel.name, session.id)
            raise _Reply(prompts.confirmation(short, project, prompts.ALREADY_ANSWERED)) from exc
        self._state.clear_prompt_messages(self._channel.name, session.id)
        if not result.ends_turn:
            self._begin(session)
        await self._post(prompts.confirmation(short, project, result.done))
        await self._notify_waiting()

    async def _answer_quoted(self, command: commands.Command) -> None:
        """The reply to one prompt message goes to that message's session, and only while that prompt is the
        one the session is showing. Otherwise nothing is typed and the user is told it was already answered."""
        found = self._state.find_prompt_message(self._channel.name, command.reply_to or "", self._clock())
        record, is_open = found if found else ({}, False)
        session = next((s for s in self._service.list() if s.id == record.get("session_id")), None)
        if session is None:
            raise _Reply(commands.system_reply(prompts.ALREADY_ANSWERED, []))
        shown = session.prompt
        if not (is_open and session.waiting and shown is not None and shown.id == record["prompt_id"]):
            raise _Reply(prompts.confirmation(session.short, session.project.name, prompts.ALREADY_ANSWERED))
        await self._answer(session, command.text)

    async def _post_prompt(self, session: Session, prompt: prompts.Prompt) -> bool:
        """One message for this session, remembered by its message id with the prompt and an expiry. A session
        started outside chat says how long it has waited."""
        now = self._clock()
        waited = None if session.from_chat else now - self._since(session)
        message_id = await self._try_post(prompts.waiting_message(session.short, session.project.name, prompt, waited=waited))
        if message_id is None:
            return False
        # Posted but the channel gave no id: remember it as sent so it is never posted twice; no reply can route to it.
        route_id = message_id or f"{UNROUTED_PREFIX}{prompt.id}"
        self._state.record_prompt_message(
            self._channel.name, route_id, session.id, prompt.id, now + PROMPT_ROUTE_SECONDS, now
        )
        return True

    async def _notify_waiting(self) -> None:
        """Posts a message for each waiting session that is due one and has a place, and names the rest once."""
        sessions = self._service.list()
        showing = {(s.id, s.prompt.id) for s in sessions if s.waiting and s.prompt is not None}
        for record in self._state.prompt_messages(self._channel.name):
            if (record["session_id"], record["prompt_id"]) not in showing:
                self._state.clear_prompt_messages(self._channel.name, record["session_id"])
        posted = {(m["session_id"], m["prompt_id"]) for m in self._state.prompt_messages(self._channel.name)}
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

    def _begin(self, session: Session) -> None:
        now = self._clock()
        self._turns[session.id] = _Turn(started=now, last_note=now)

    async def _on_event(self, event: Event) -> None:
        session = event.session
        turn = self._turns.pop(session.id, None)
        if not self.live:
            return
        short = session.short
        several = self._several(session)
        project = session.project.name
        self._state.clear_prompt_messages(self._channel.name, session.id)
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
        self._sync_guard()
        if self._master.active():
            self._not_armed_noticed = False
        if self._master.expired():
            await self._expire()
        elif self.live:
            await self._warn_if_due()
        if self.live:
            if self._anyone_waiting():
                self._window.hold()
            await self._close_if_expired()
            await self._report_progress()
        await self._service.tick()
        if self.live:
            await self._notify_waiting()

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
