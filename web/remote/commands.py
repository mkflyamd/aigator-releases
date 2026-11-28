"""The @gator command grammar and reply formatting, independent of any channel.

Every message Gator posts follows the copy deck: the prefix and state on line 1, the body, a blank
line, then a `Next:` block of options. Every post opens with the crocodile marker `[🐊`; the loop guard keys on it."""

from __future__ import annotations

import math
import re
import time
from dataclasses import dataclass
from datetime import datetime

from remote import settings

TRIGGER_RE = re.compile(r"^\s*@gator(?:\s+(.*))?$", re.IGNORECASE | re.DOTALL)
_ASKING_RE = re.compile(r"^what(?:'s|’s| is)\s+(?:the\s+)?", re.IGNORECASE)
GREETING_WORDS = ("hi", "hello", "hey", "start")
INTERRUPT_WORDS = ("esc", "escape")
RESERVED = ("list", "status", "stop", "help", "bye", *INTERRUPT_WORDS, *GREETING_WORDS)
WINDOW_SECONDS = 30 * 60.0
NAME_MAX_CHARS = 40
TEXT_MAX_BYTES = 4096
REPLY_MAX_CHARS = 3500
REPLY_CEILING_CHARS = 60000
REPLY_MAX_PARTS = 12
UNTAGGED_MAX_CHARS = 1500
EVERYTHING_GOES_TO_AGENT = "Everything you type here goes to the agent."
TOO_LONG_BODY = f"Not sent: over {UNTAGGED_MAX_CHARS} characters."
TOO_LONG_OPTIONS = [f"Add `@gator` to send up to {TEXT_MAX_BYTES}.", "Or shorten it and send it again."]
ATTACHMENT_BODY = "Attachments are not sent from this chat."
ATTACHMENT_OPTION = "Describe what you need in text, and send that."
SETTINGS_SECTION = "Remote control"
CROC = "\U0001F40A"
MARKER = f"[{CROC}"
MARKER_SHORTCODE = "[:crocodile:"
LEGACY_PREFIX = "[Gator"
BULLET = "•"
DOT = "·"
CHOICES_SHOWN = 2
CHOICE_MAX_CHARS = 60
WORKING, WAITING, IDLE = "working", "waiting for you", "idle"
ACK_DELAY_SECONDS = 5.0
PROGRESS_SECONDS = 300.0
ELAPSED_MIN_SECONDS = 60.0
SLEEPING, FAILED = "sleeping", "failed"
BREVITY_HINT = "(This session was started from a chat app. Keep replies short, in plain text, with no tables.)"
_CHOICE_RE = re.compile(r"^\s*(?:\d{1,2}|[A-Za-z])[.)]\s+(.+?)\s*$")
LEGACY_OWN_RE = re.compile(r"^\[[^\]\r\n]{0,80}\] " + CROC)
UNKNOWN_MENTION_SHOWN = 3
PEERS_SHOWN = 8
WAITING_HEADLINE = "Waiting for your answer."
LEADING_MENTION_RE =re.compile(r"^@([\w.-]+):?(?:\s+(.*))?$", re.DOTALL)


@dataclass(frozen=True)
class Command:
    kind: str  # send | list | status | stop | stop_all | help | open | bye | answer | interrupt
    name: str | None = None
    text: str = ""
    reply_to: str | None = None  # answer: the id of the posted prompt message this reply is for
    tagged: bool = True  # False for an ordinary message routed by the open chat window
    sent_at: float = 0.0  # when the user wrote it, as the channel says; 0 when it does not


def _cap_bytes(text: str) -> str:
    return text.encode("utf-8")[:TEXT_MAX_BYTES].decode("utf-8", "ignore")


def _reserved_phrase(rest: str) -> str:
    """`status?`, `what is the status` and `what's the list?` read as the reserved word. Only a reserved word
    alone, or `status`/`stop` with one name, is rewritten; any other text goes to the agent as typed."""
    plain = _ASKING_RE.sub("", rest.rstrip(".!?, ").strip())
    words = plain.split()
    if words and words[0].lower() in RESERVED and (len(words) == 1 or (len(words) == 2 and words[0].lower() in ("status", "stop"))):
        return plain
    return rest


def parse(message: str) -> Command | None:
    """None for anything that is not an `@gator` command (an ordinary note)."""
    match = TRIGGER_RE.match(message or "")
    if not match:
        return None
    rest = _cap_bytes((match.group(1) or "").strip())
    if not rest:
        return Command("help")
    rest = _reserved_phrase(rest)
    whole = rest.rstrip(".!?, ").lower()
    if whole in GREETING_WORDS:
        return Command("open")
    if whole == "bye":
        return Command("bye")
    word, _, tail = rest.partition(" ")
    tail = tail.strip()
    key = word.lower()
    if key == "stop" and tail.lower() == "all":
        return Command("stop_all")
    if key in ("status", "stop", *INTERRUPT_WORDS):
        return Command("interrupt" if key in INTERRUPT_WORDS else key, name=tail.split()[0].lower() if tail else None)
    if key in ("list", "help"):
        return Command(key)
    return Command("send", text=rest)


def next_block(options: list[str]) -> str:
    return "Next:\n" + "\n".join(f"{BULLET} {option}" for option in options)


def _tidy(text: str) -> str:
    """No trailing spaces and never more than one blank line in a row, so chat apps do not stretch the message."""
    lines = [line.rstrip() for line in text.replace("\r\n", "\n").replace("\r", "\n").split("\n")]
    return re.sub(r"\n{3,}", "\n\n", "\n".join(lines)).strip()


def app_prefix() -> str:
    """The app voice: `[🐊 Gator]`."""
    return f"[{CROC} {settings.agent_name()}]"


def system_reply(body: str, options: list[str], *, after: str = "") -> str:
    """An app notice: the state and body, a blank line, the Next block, then an optional closing line."""
    tail = f"\n\n{after}" if after else ""
    choices = f"\n\n{next_block(options)}" if options else ""
    return _tidy(f"{app_prefix()} {body}{choices}{tail}")


def agent_prefix(session: str, project: str | None = None, several: bool = False) -> str:
    """`[🐊 Gator - {project}]`, or `[🐊 Gator - {session} - {project}]` while several sessions are live.
    The project slot is always there: it is what tells an agent reply from the app voice."""
    project = project or session
    tag = f"{session} - {project}" if several else project
    return f"[{CROC} {settings.agent_name()} - {tag}]"


def agent_reply(
    session: str, text: str, options: list[str], *, project: str | None = None, several: bool = False
) -> str:
    tail = f"\n\n{next_block(options)}" if options else ""
    return _tidy(f"{agent_prefix(session, project, several)} {text.strip()}{tail}")


def is_own_message(text: str) -> bool:
    """A message Gator wrote: it starts with the crocodile marker (as the emoji or Slack's shortcode), whatever
    the configured name. The older `[Gator` and `[label] 🐊` starts count too, so earlier posts stay ignored."""
    text = text.lstrip()
    return text.startswith((MARKER, MARKER_SHORTCODE, LEGACY_PREFIX)) or bool(LEGACY_OWN_RE.match(text))


def in_words(seconds: float) -> str:
    """A span in words for chat copy: "24 hours", "10 minutes", "30 seconds"."""
    total = max(1, math.ceil(seconds))
    if total % 3600 == 0:
        n, unit = total // 3600, "hour"
    elif total >= 60:
        n, unit = math.ceil(total / 60), "minute"
    else:
        n, unit = total, "second"
    return f"{n} {unit}{'' if n == 1 else 's'}"


def clock_time(epoch: float) -> str:
    return datetime.fromtimestamp(epoch).strftime("%H:%M")


def _quiet_note() -> str:
    return f"It also closes after {in_words(WINDOW_SECONDS)} of quiet."


def _tip_options(chat_open: bool) -> list[str]:
    tag = "" if chat_open else "@gator "
    first = (
        "Type a request and it runs in your Claude session."
        if chat_open
        else "`@gator hi` to open this chat, then skip `@gator`."
    )
    last = f"`{tag}bye` to close this chat." if chat_open else "`@gator <request>` runs it in your Claude session."
    return [
        first,
        f"`{tag}list` to see what is running.",
        f"`{tag}status` to see what each session is doing.",
        f"`{tag}stop all` to stop everything and turn Remote control off.",
        last,
    ]


def greeting() -> str:
    return system_reply(
        f"Gator on watch. This chat is open, so you can skip `@gator`.\n{EVERYTHING_GOES_TO_AGENT}",
        _tip_options(True),
        after=_quiet_note(),
    )


def too_long() -> str:
    return system_reply(TOO_LONG_BODY, TOO_LONG_OPTIONS)


def attachment_not_sent() -> str:
    return system_reply(ATTACHMENT_BODY, [ATTACHMENT_OPTION])


def help_text(chat_open: bool = True) -> str:
    if chat_open:
        return system_reply("Here is what you can type.", _tip_options(True))
    return system_reply("This chat is closed, so start each message with `@gator`.", _tip_options(False))


def already_open() -> str:
    return system_reply("This chat is already open.", ["Type a request to run it.", "`help` to see all options."])


def chat_closed_quiet() -> str:
    return system_reply(
        f"Chat closed after {in_words(WINDOW_SECONDS)} of quiet.", ["`@gator hi` to open it again."]
    )


def chat_closed_bye() -> str:
    return system_reply("Chat closed. Gator out.", ["`@gator hi` to open it again."])


def timed_out(seconds: float) -> str:
    return system_reply(
        f"Remote control turned itself off after {in_words(seconds)}.",
        [f"Open AI Gator, then Settings, then {SETTINGS_SECTION}, and switch it on."],
    )


def turns_off_soon(seconds: float) -> str:
    return system_reply(
        f"Remote control turns off in {in_words(seconds)}.",
        [f"Need more time? Open AI Gator, then Settings, then {SETTINGS_SECTION}, and turn it back on."],
    )


def not_armed() -> str:
    return system_reply(
        "Not sent: Remote control is not turned on.",
        [f"Open AI Gator, then Settings, then {SETTINGS_SECTION}, and switch it on."],
    )


def timed_out_reply(seconds: float) -> str:
    return system_reply(
        f"Not sent: Remote control timed out after {in_words(seconds)}.",
        [f"Open AI Gator, then Settings, then {SETTINGS_SECTION}, and switch it on."],
    )


def slow_down(wait_seconds: float, dropped: int = 1) -> str:
    if dropped == 1:
        return system_reply(
            "Not sent: too many messages at once.", [f"Wait {in_words(wait_seconds)}, then send it again."]
        )
    return system_reply(
        f"Not sent: {dropped} messages, because too many came at once.",
        [f"Wait {in_words(wait_seconds)}, then send them again."],
    )


def part_not_sent(number: int, total: int) -> str:
    return system_reply(
        f"Part {number} of {total} did not send.", ["Ask for the reply again, or open the agent's tab in AI Gator."]
    )


def stale_skipped(count: int, limit_seconds: float) -> str:
    one = count == 1
    what = "a message" if one else f"{count} messages"
    return system_reply(
        f"Not sent: {what} you sent while AI Gator was off, because {'it was' if one else 'they were'} "
        f"more than {in_words(limit_seconds)} old.",
        ["Send it again if you still need it." if one else "Send them again if you still need them."],
    )


def online() -> str:
    return system_reply("Online.", ["`@gator hi` to open a chat."])


def restarted(running: int, asleep: int) -> str:
    return system_reply(f"Gator restarted: {running} running, {asleep} asleep.", ["`list` to see them."])


def reconnected(channel: str, seconds: float, reason: str) -> str:
    return system_reply(
        f"Back online. Gator could not reach {channel.title()} for {in_words(seconds)}: {reason}",
        ["`list` to see what is running."],
    )


def error_reply(text: str) -> str:
    return system_reply(text, ["`help` to see what you can do."])


def stopped(count: int) -> str:
    return system_reply(
        f"Stopped {count} session{'' if count == 1 else 's'}. Remote control is off.",
        ["Open AI Gator and turn Remote control on again."],
    )


def stop_all_failed(still_running: str, stopped_names: str) -> str:
    done = f" Stopped: {stopped_names}." if stopped_names else ""
    return system_reply(
        f"Could not stop {still_running}; still running.{done} Remote control stays on.", ["`stop all` to try again."]
    )


def no_sessions() -> str:
    return system_reply("No remote sessions are running.", ["Send a request and it starts a new session."])


def session_not_found(name: str) -> str:
    """The user-typed name is echoed back, so it is flattened to one line and capped."""
    shown = " ".join(name.split())[:NAME_MAX_CHARS]
    return system_reply(f"No session named {shown}.", ["`list` to see what is running."])


def _same_name(name: str, project: str) -> bool:
    return re.sub(r"[^a-z0-9]+", "-", project.lower()).strip("-") == name


def session_list(
    rows: list[tuple[str, str, str, float, str]],
    peers: list[tuple[str, str]] | None = None,
    more: int = 0,
    reach: str = "",
) -> str:
    """rows are (name, project, state, seconds in that state, what to type to answer it). Grouped as the
    History pane groups them, the longest wait first; the project is left out when it is the name. peers
    are other agents in the project as (name, state), already capped; `more` is how many were left out and
    `reach` is a name that can be typed to message one of them."""
    peers = peers or []
    if not rows and not peers:
        return no_sessions()
    lines, number = [], 0
    if rows:
        lines.append(f"{len(rows)} session{'' if len(rows) == 1 else 's'} running:")
    else:
        lines.append("No remote sessions are running.")
    waiting = sorted((r for r in rows if r[2] == WAITING), key=lambda r: -r[3])
    groups = (
        ("Needs you:", waiting),
        ("Working:", [r for r in rows if r[2] == WORKING]),
        ("Idle:", [r for r in rows if r[2] == IDLE]),
        ("Not running:", [r for r in rows if r[2] in (SLEEPING, FAILED)]),
    )
    for title, group in groups:
        if group:
            lines.append(title)
        for name, project, state, seconds, _ in group:
            number += 1
            where = "" if _same_name(name, project) else f" {DOT} {project}"
            if state in (SLEEPING, FAILED):
                lines.append(f"{number}. {name}{where} {DOT} {state}")
                continue
            lead = "waiting " if state == WAITING else ""
            lines.append(f"{number}. {name}{where} {DOT} {lead}{elapsed_words(seconds)}")
    if peers:
        lines.append("\nOther agents in this project:")
        lines.extend(f"- {name} {DOT} {state}" for name, state in peers)
        if more:
            lines.append(f"- {more} more.")
    options = []
    if waiting:
        name, answer = waiting[0][0], waiting[0][4]
        what = "to allow once." if answer == "allow" else "to answer the longest-waiting one."
        options.append(f"`{name}: {answer}` {what}")
    elif not rows:
        options.append("Send a request and it starts a new session.")
    else:
        asleep = next((r[0] for r in rows if r[2] == SLEEPING), None)
        if asleep:
            options.append(f"`{asleep}: your message` to wake it.")
    if peers:
        options.append(f"`@gator {reach or peers[0][0]} your message` to message another agent.")
    return system_reply("\n".join(lines), options)


def peer_label(name: str) -> str:
    """A session name from outside this chat: one line, no brackets, capped. It is shown inside the
    `[name - project]` prefix, so it must not be able to end that prefix early or fake another one."""
    one_line = " ".join(name.replace("[", "(").replace("]", ")").split())
    return one_line.replace(" - ", " / ")[:NAME_MAX_CHARS]


def peer_sent(name: str, woke: bool) -> str:
    body = f"Woke {peer_label(name)} and sent your message." if woke else f"Sent to {peer_label(name)}."
    return system_reply(body, ["Its reply comes back here when it finishes."])


def peer_prefix(name: str, project: str) -> str:
    """`[🐊 {peer} - {project}]`: an agent that is not Remote's own, labelled with its name and project.
    It starts with the crocodile marker, so the loop guard ignores it. A peer that carries Gator's own
    name, alone or followed by more words, is told apart so it cannot pass for Remote's agent."""
    label = peer_label(name)
    own = settings.agent_name().casefold()
    folded = label.casefold()
    if folded.startswith(own) and not folded[len(own) :][:1].isalnum():
        label = f"{label} (other agent)"
    return f"[{CROC} {label} - {peer_label(project)}]"


def peer_exited(name: str, project: str) -> str:
    return _tidy(
        f"{peer_prefix(name, project)} It closed before it answered.\n\n"
        + next_block(["`@gator list` to see which agents are running."])
    )


def peer_result(name: str, project: str, text: str, waiting: bool = False, ref: str | None = None) -> list[str]:
    """Another agent's answer to a message sent from chat, under its own name. `text` has already been
    through the same redaction as Remote's own replies. `ref` is what the person types to reach it."""
    return agent_result(
        "Claude",
        name,
        WAITING_HEADLINE if waiting else "",
        text,
        waiting,
        prefix=peer_prefix(name, project),
        reply_to=f"@gator {ref or peer_label(name)} ",
    )


def which_prompt() -> str:
    """More than one session waits on a prompt and the reply names none of them."""
    return system_reply("Several sessions are waiting on you. Which one?", ["Reply to the message of the one you mean."])


def peer_refused(name: str, reason: str, permanent: bool = False) -> str:
    """Nothing was typed. A refusal that time can mend says to send again; one it cannot only points at `list`."""
    options = ["`list` to see the agents you can message."]
    if not permanent:
        options.insert(0, "Send it again in a moment.")
    return system_reply(f"Did not send to {peer_label(name)}. {reason}", options)


def peer_limit(name: str, limit: int, wait_seconds: float) -> str:
    return system_reply(
        f"That is {limit} messages to {peer_label(name)} in the last hour, the most allowed. Not sent.",
        [f"Wait {in_words(wait_seconds)}, then send it again.", f"Raise the limit in Settings, under {SETTINGS_SECTION}."],
    )


def peer_ambiguous(name: str, choices: list[tuple[str, str]]) -> str:
    """Several agents share a name. choices are (short id, state); the id is what to type instead."""
    lines = [f"- `{short}` {DOT} {state}" for short, state in choices]
    return system_reply(
        f"More than one agent is called {peer_label(name)}:\n" + "\n".join(lines),
        [f"`{choices[0][0]} your message` to pick one by its id."],
    )


def which_session(names: list[str]) -> str:
    """Several sessions are running and none, or more than one, is waiting: ask which one."""
    options = [f"`{name}: your message`" for name in names[:CHOICES_SHOWN]] + ["`list` to see them all."]
    return system_reply("Which session?", options)


def nothing_to_cancel() -> str:
    return system_reply("Nothing is waiting on a prompt, so there is nothing to cancel.", ["`status` to see what each session is doing."])


def which_to_cancel(names: list[str]) -> str:
    options = [f"`esc {name}`" for name in names[:CHOICES_SHOWN]]
    return system_reply("Several sessions are waiting on a prompt. Which one should be cancelled?", options)


def which_to_stop(names: list[str]) -> str:
    options = [f"`stop {name}`" for name in names[:CHOICES_SHOWN]] + ["`stop all` to stop everything and turn Remote control off."]
    return system_reply("Which session should stop?", options)


def unknown_mention(name: str, known: list[str]) -> str:
    """A leading @name that is not a session. Sent nowhere; the options are the sessions that exist."""
    shown = " ".join(name.split())[:NAME_MAX_CHARS]
    body = f"I don't know {shown}. Start with `@gator` to send it to the agent."
    if not known:
        return _tidy(f"{app_prefix()} {body}")
    return system_reply(body, [f"`{n}: your message`" for n in known[:UNKNOWN_MENTION_SHOWN]])


def mention_needs_text(name: str) -> str:
    return system_reply(f"What should {name} do?", [f"`{name}: your message`"])


def session_status(
    session: str,
    state: str,
    since: float,
    last_activity: float,
    *,
    project: str | None = None,
    several: bool = False,
    now: float | None = None,
    last_step: str = "",
) -> str:
    last = f"Last activity {clock_time(last_activity)}."
    if state == SLEEPING:
        text, options = f"Asleep to free memory.\n{last}", ["Reply here to wake it.", f"`stop {session}` to stop it."]
    elif state == FAILED:
        text, options = f"Could not be woken.\n{last}", [f"`stop {session}`, then send a message to start a new one."]
    elif state == WORKING:
        text = f"Working for {elapsed_words((time.time() if now is None else now) - since)}."
        text += f" Last step: {last_step}." if last_step else ""
        options = [_stop_option(session, several)]
    else:
        lead = {WAITING: "Waiting for you", IDLE: "Idle"}[state]
        text, options = f"{lead} since {clock_time(since)}.", []
        if clock_time(last_activity) != clock_time(since):
            text += f"\n{last}"
    return agent_reply(session, text, options, project=project, several=several)


def _stop_option(session: str, several: bool) -> str:
    return f"`stop{f' {session}' if several else ''}` to stop it."


def busy_queued(
    session: str, elapsed: float, last_step: str, *, project: str | None = None, several: bool = False
) -> str:
    """The reply to a message that arrives while the session is still working: what it is doing, and that the
    message is queued behind it."""
    body = f"Working for {elapsed_words(elapsed)}."
    body += f" Last step: {last_step}." if last_step else ""
    body += "\nYour message is queued, so no need to resend."
    return agent_reply(session, body, [_stop_option(session, several)], project=project, several=several)


def working_ack(session: str, text: str, *, project: str | None = None, several: bool = False) -> str:
    options = [f"`status {session}` to see what it is doing.", f"`stop {session}` to stop it."]
    return agent_reply(session, text, options, project=project, several=several)


def working(session: str, branch: str | None, several: bool, *, project: str | None = None) -> str:
    """The one message sent when a turn has not finished after ACK_DELAY_SECONDS."""
    body = "Working on it." + (f"\nBranch: {branch}" if branch else "")
    return agent_reply(session, body, [_stop_option(session, several)], project=project, several=several)


def elapsed_words(seconds: float) -> str:
    """Like 2 min, 12 min or 1 h 5 min: no seconds once past a minute."""
    hours, minutes = divmod(max(1, int(seconds // 60)), 60)
    if hours and minutes:
        return f"{hours} h {minutes} min"
    return f"{hours} h" if hours else f"{minutes} min"


def progress(
    session: str, elapsed: float, last_step: str = "", *, project: str | None = None, several: bool = False
) -> str:
    body = f"Still working, {elapsed_words(elapsed)}."
    body += f" Last step: {last_step}." if last_step else ""
    return agent_reply(session, body, [], project=project, several=several)


def done_headline(elapsed: float | None) -> str:
    if elapsed is None or elapsed <= ELAPSED_MIN_SECONDS:
        return "Done."
    return f"Done in {elapsed_words(elapsed)}."


def asks_a_question(text: str) -> bool:
    """True when the agent's last line is a question, or the line above a closing list of options is."""
    lines = [line for line in text.strip().splitlines() if line.strip()]
    run = 0
    for line in reversed(lines):
        if not _CHOICE_RE.match(line):
            break
        run += 1
    if run >= CHOICES_SHOWN:
        lines = lines[:-run]
    return bool(lines) and lines[-1].rstrip().rstrip("`*_\"')").endswith("?")


def agent_stopped(session: str, *, project: str | None = None, several: bool = False) -> str:
    options = ["Send a message to start it again.", "`list` to see what is running."]
    return agent_reply(session, "Stopped.", options, project=project, several=several)


def waking(session: str, *, project: str | None = None, several: bool = False) -> str:
    """Posted the moment a message reaches a sleeping session, before the wake finishes."""
    return agent_reply(
        session,
        "Waking this session. Your message goes in when it is up, so no need to resend.",
        [f"`status {session}` to check on it."],
        project=project,
        several=several,
    )


def wake_failed(
    session: str, reason: str = "The session could not be woken.", *, permanent: bool = False,
    project: str | None = None, several: bool = False,
) -> str:
    """Nothing was sent. A transient failure can be retried by sending again; a permanent one cannot."""
    option = (
        f"`stop {session}`, then send a message to start a new session."
        if permanent
        else f"Send your message again to retry, or `stop {session}`."
    )
    return agent_reply(session, f"Nothing was sent.\n{reason}", [option], project=project, several=several)


def lane_moved_on(session: str, *, project: str | None = None, several: bool = False) -> str:
    """The lane's saved session is open in another terminal and cannot take the message, so a new session did."""
    return agent_reply(
        session,
        "Started a new session for this. The saved one is open in another terminal on this computer, so it was left alone.",
        ["Reply here to keep going in the new session."],
        project=project,
        several=several,
    )


def still_waking(session: str, *, project: str | None = None, several: bool = False) -> str:
    """A message that arrives while the wake is under way: it is queued behind the first one."""
    return agent_reply(
        session,
        "Still waking up. Your message is queued, so no need to resend.",
        [f"`status {session}` to check on it."],
        project=project,
        several=several,
    )


WAKE_QUEUE_MAX = 10


def wake_queue_full(session: str, *, project: str | None = None, several: bool = False) -> str:
    return agent_reply(
        session,
        f"Not sent: {WAKE_QUEUE_MAX} messages are already waiting for it to wake. Send this one again once it is up.",
        [f"`status {session}` to check on it."],
        project=project,
        several=several,
    )


def queued_not_sent(session: str, count: int, *, project: str | None = None, several: bool = False) -> str:
    """The wake failed after messages were promised a place behind the first one."""
    noun = "message" if count == 1 else "messages"
    return agent_reply(
        session,
        f"{count} queued {noun} not sent.",
        [f"Send {'it' if count == 1 else 'them'} again to retry, or `stop {session}`."],
        project=project,
        several=several,
    )


def wake_too_soon(session: str, wait_seconds: float, *, project: str | None = None, several: bool = False) -> str:
    return agent_reply(
        session,
        "Could not be woken a moment ago. Nothing was sent.",
        [f"Try again in {int(wait_seconds) + 1} seconds."],
        project=project,
        several=several,
    )


def already_has_session(session: str, *, project: str | None = None, several: bool = False) -> str:
    return agent_reply(
        session,
        "Already has a session in this project.",
        [f"`{session}: your message` to use it.", f"`stop {session}` to end it first."],
        project=project,
        several=several,
    )


def send_failed(
    session: str, reason: str, *, permanent: bool = False, project: str | None = None, several: bool = False
) -> str:
    option = (
        f"`stop {session}`, then send a message to start a new session."
        if permanent
        else f"Send your message again to retry, or `stop {session}`."
    )
    return agent_reply(session, f"Nothing was sent.\n{reason}", [option], project=project, several=several)


def duplicate_lane(session: str, *, project: str | None = None, several: bool = False) -> str:
    """A second running terminal for a project that already has a remote session."""
    return agent_reply(
        session,
        "A second remote terminal for this project is running. It was left alone, and chat cannot manage it.",
        ["Close it in AI Gator."],
        project=project,
        several=several,
    )


LANE_REPLACED_REASON = "A newer remote terminal for this project replaced this lane."


def lane_replaced(session: str, *, project: str | None = None, several: bool = False) -> str:
    """After a restart a newer terminal was found for a project whose lane still has a saved session."""
    return agent_reply(
        session,
        f"{LANE_REPLACED_REASON} Its saved session was kept, and the newer terminal was left running.",
        [f"`stop {session}` to clear the saved session.", "Close the newer terminal in AI Gator if it is not wanted."],
        project=project,
        several=several,
    )


def no_default_project() -> str:
    return system_reply(
        "No default project is set, so there is nowhere to start a session.",
        [f"Pick a default project in AI Gator {SETTINGS_SECTION} settings."],
    )


def command_failed() -> str:
    return system_reply("That command failed and was not retried.", ["`help` to see what you can do."])


def lane_lost(session: str, *, project: str | None = None, several: bool = False) -> str:
    return agent_reply(
        session, "The saved session is gone.", ["Send a message to start a new session."], project=project, several=several
    )


def agent_exited(session: str, *, project: str | None = None, several: bool = False) -> str:
    return agent_reply(
        session, "The agent process exited.", ["Send a message to start a new session."], project=project, several=several
    )


def _choices(question: str) -> list[str]:
    """Exactly two short numbered or lettered options at the end of an agent's question. Anything that
    would read as a Gator command when typed back (stop, list, ...) is not offered."""
    run: list[str] = []
    for line in reversed([line for line in question.strip().splitlines() if line.strip()]):
        match = _CHOICE_RE.match(line)
        if not match:
            break
        run.append(match.group(1).replace("`", "").strip(" *_"))
    run.reverse()
    if len(run) != CHOICES_SHOWN or not all(0 < len(c) <= CHOICE_MAX_CHARS for c in run):
        return []
    if any((parse(f"@gator {c}") or Command("send")).kind != "send" for c in run):
        return []
    return run


def _split(body: str) -> list[str]:
    """The body in pieces of at most REPLY_MAX_CHARS, each cut at a paragraph boundary when one is in reach, else
    at a line, else at whitespace, never inside a word. A code fence left open by a cut is closed and opened again."""
    pieces: list[str] = []
    rest = body
    while len(rest) > REPLY_MAX_CHARS:
        window = rest[:REPLY_MAX_CHARS]
        cuts = [window.rfind(boundary) for boundary in ("\n\n", "\n", " ")]
        cut = next((c for c in cuts if c > REPLY_MAX_CHARS // 2), max(cuts))
        cut = cut if cut > 0 else REPLY_MAX_CHARS
        piece, rest = rest[:cut].rstrip(), rest[cut:].lstrip()
        if piece.count("```") % 2:
            piece += "\n```"
            rest = "```\n" + rest
        pieces.append(piece)
    pieces.append(rest)
    return pieces


def agent_result(
    agent: str,
    session: str,
    headline: str,
    text: str,
    waiting: bool = False,
    several: bool = False,
    *,
    project: str | None = None,
    prefix: str | None = None,
    reply_to: str | None = None,
) -> list[str]:
    """A turn's outcome as the messages to post, in order. An empty headline is a quick answer: the prefix and the
    agent's words, nothing else. Otherwise the headline, then the agent's words on the next line. A reply over
    REPLY_MAX_CHARS is never cut: it goes out in parts, each with the prefix and `(n/N)` ending its first line.
    Only a reply past REPLY_MAX_PARTS parts stops, and says so in its last part. A question ends with its choices as
    options; an empty reply ends with what the user can do."""
    prefix = prefix or agent_prefix(session, project, several)
    body = _tidy(text)
    answer = f"`{reply_to}your answer` to answer it." if reply_to else "Type your answer."
    keep_going = f"`{reply_to}your message` to keep going." if reply_to else "Reply here to keep going in this session."
    if not body:
        options = [f"Open the {agent} tab in AI Gator to see it.", answer if waiting else keep_going]
        return [_tidy(f"{prefix} {headline or 'Done.'} No text came back.\n\n{next_block(options)}")]
    ceiling = len(body) > REPLY_CEILING_CHARS
    if ceiling:
        body = body[:REPLY_CEILING_CHARS].rsplit(" ", 1)[0]
    pieces = _split(body)
    if len(pieces) > REPLY_MAX_PARTS:
        ceiling, pieces = True, pieces[:REPLY_MAX_PARTS]
    if ceiling:
        pieces[-1] += (
            f"\n\nThis reply is longer than {REPLY_MAX_PARTS} messages, so the rest was not sent."
            f" Open the {agent} tab in AI Gator for all of it."
        )
    tag = reply_to if reply_to is not None else (f"{session}: " if several else "")
    options = [f"`{tag}{c}`" for c in _choices(body)] if waiting and headline else []
    tail = f"\n\n{next_block(options)}" if options else ""
    count = len(pieces)
    parts = []
    for number, piece in enumerate(pieces, 1):
        more = f" ({number}/{count})" if count > 1 else ""
        if headline:
            head = f"{prefix} {headline}{more}\n{piece}"
        elif count > 1:
            head = f"{prefix}{more}\n{piece}"
        else:
            head = f"{prefix} {piece}"
        parts.append(_tidy(head + (tail if number == count else "")))
    return parts
