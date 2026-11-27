"""The @gator command grammar and reply formatting, independent of any channel.

Every message Gator posts follows the copy deck: the prefix and state on line 1, the body, a blank
line, then a `Next:` block of options. SYSTEM_PREFIX is the one prefix constant; the loop guard reads it."""

from __future__ import annotations

import math
import re
from dataclasses import dataclass
from datetime import datetime

TRIGGER_RE = re.compile(r"^\s*@gator(?:\s+(.*))?$", re.IGNORECASE | re.DOTALL)
GREETING_WORDS = ("hi", "hello", "hey", "start")
RESERVED = ("list", "status", "stop", "help", "bye", *GREETING_WORDS)
WINDOW_SECONDS = 30 * 60.0
NAME_MAX_CHARS = 40
TEXT_MAX_BYTES = 4096
REPLY_MAX_CHARS = 3500
LEAD_MAX_CHARS = 200
UNTAGGED_MAX_CHARS = 1500
EVERYTHING_GOES_TO_AGENT = "Everything you type here goes to the agent."
NOT_SENT_BODY = "That message was not sent to the agent because it is long or has an attachment."
NOT_SENT_OPTION = "`@gator <request>` sends a request on purpose."
SYSTEM_PREFIX = "[Gator"
SETTINGS_SECTION = "Remote control"
CROC = "\U0001F40A"
BULLET = "•"
DOT = "·"
CHOICES_SHOWN = 2
CHOICE_MAX_CHARS = 60
WORKING, WAITING, IDLE = "working", "waiting for you", "idle"
_CHOICE_RE = re.compile(r"^\s*(?:\d{1,2}|[A-Za-z])[.)]\s+(.+?)\s*$")


@dataclass(frozen=True)
class Command:
    kind: str  # send | list | status | stop | stop_all | help | open | bye
    name: str | None = None
    text: str = ""


def _cap_bytes(text: str) -> str:
    return text.encode("utf-8")[:TEXT_MAX_BYTES].decode("utf-8", "ignore")


def parse(message: str) -> Command | None:
    """None for anything that is not an `@gator` command (an ordinary note)."""
    match = TRIGGER_RE.match(message or "")
    if not match:
        return None
    rest = _cap_bytes((match.group(1) or "").strip())
    if not rest:
        return Command("help")
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
    if key in ("status", "stop"):
        return Command(key, name=tail.split()[0].lower() if tail else None)
    if key in ("list", "help"):
        return Command(key)
    return Command("send", text=rest)


def next_block(options: list[str]) -> str:
    return "Next:\n" + "\n".join(f"{BULLET} {option}" for option in options)


def system_reply(body: str, options: list[str], *, croc: bool = False, after: str = "") -> str:
    """A [Gator] notice: the state and body, a blank line, the Next block, then an optional closing line."""
    mark = f" {CROC}" if croc else ""
    tail = f"\n\n{after}" if after else ""
    return f"{SYSTEM_PREFIX}]{mark} {body}\n\n{next_block(options)}{tail}"


def agent_reply(agent: str, project: str, text: str, options: list[str]) -> str:
    return f"{SYSTEM_PREFIX} - {agent} - {project}] {text.strip()}\n\n{next_block(options)}"


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
        f"`{tag}stop all` to stop everything.",
        last,
    ]


def greeting() -> str:
    return system_reply(
        f"Gator on watch. This chat is open, so you can skip `@gator`.\n{EVERYTHING_GOES_TO_AGENT}",
        _tip_options(True),
        croc=True,
        after=_quiet_note(),
    )


def not_sent() -> str:
    return system_reply(NOT_SENT_BODY, [NOT_SENT_OPTION])


def help_text(chat_open: bool = True) -> str:
    if chat_open:
        return system_reply(
            f"This chat is open, so you can skip `@gator`.\n{EVERYTHING_GOES_TO_AGENT}",
            _tip_options(True),
            after=_quiet_note(),
        )
    return system_reply("This chat is closed, so start each message with `@gator`.", _tip_options(False))


def already_open() -> str:
    return system_reply("This chat is already open.", ["Type a request to run it.", "`help` to see all options."])


def chat_closed_quiet() -> str:
    return system_reply(
        f"Chat closed after {in_words(WINDOW_SECONDS)} of quiet.", ["`@gator hi` to open it again."], croc=True
    )


def chat_closed_bye() -> str:
    return system_reply("Chat closed. Gator out.", ["`@gator hi` to open it again."], croc=True)


def timed_out(seconds: float) -> str:
    return system_reply(
        f"Remote control turned itself off after {in_words(seconds)}.",
        [f"Open AI Gator, then Settings, then {SETTINGS_SECTION}, and switch it on."],
    )


def slow_down(wait_seconds: float) -> str:
    return system_reply(
        "Slow down, that was too many messages at once.", [f"Wait {in_words(wait_seconds)}, then send it again."]
    )


def stale_skipped(count: int, limit_seconds: float) -> str:
    one = count == 1
    what = "a message" if one else f"{count} messages"
    return system_reply(
        f"Skipped {what} you sent while AI Gator was off, because it was more than {in_words(limit_seconds)} old.",
        ["Send it again if you still need it." if one else "Send them again if you still need them."],
    )


def online() -> str:
    return system_reply("Online.", ["`@gator hi` to open a chat."])


def error_reply(text: str) -> str:
    return system_reply(text, ["`help` to see what you can do."])


def stopped(count: int) -> str:
    """`stop all` also switches remote control off, so the way back is Settings, not a new request."""
    body = f"Stopped {count} session{'' if count == 1 else 's'}."
    return system_reply(
        body, [f"Open AI Gator, then Settings, then {SETTINGS_SECTION}, and switch it off and on to start again."]
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


def session_list(rows: list[tuple[str, str, str]]) -> str:
    """rows are (name, project, state); state is one of WORKING, WAITING, IDLE."""
    if not rows:
        return no_sessions()
    head = f"{len(rows)} session{'' if len(rows) == 1 else 's'} running:"
    lines = [f"{i}. {name} {DOT} {project} {DOT} {state}" for i, (name, project, state) in enumerate(rows, 1)]
    waiting = next((name for name, _, state in rows if state == WAITING), None)
    first = (
        f"`{waiting}: your answer` to answer the one that is waiting."
        if waiting
        else f"`{rows[0][0]}: your request` to talk to a session."
    )
    return system_reply("\n".join([head, *lines]), [first, f"`status {rows[0][0]}` for details.", "`stop all` to stop everything."])


def which_session(names: list[str]) -> str:
    """Several sessions are running and none, or more than one, is waiting: ask which one."""
    options = [f"`{name}: your message`" for name in names[:CHOICES_SHOWN]] + ["`list` to see them all."]
    return system_reply("Which session?", options)


def which_to_stop(names: list[str]) -> str:
    options = [f"`stop {name}`" for name in names[:CHOICES_SHOWN]] + ["`stop all` to stop everything."]
    return system_reply("Which session should stop?", options)


def session_status(agent: str, name: str, state: str, since: float, last_activity: float) -> str:
    lead = {WORKING: "Working", WAITING: "Waiting for you", IDLE: "Idle"}[state]
    text = f"{lead} since {clock_time(since)}.\nLast activity {clock_time(last_activity)}."
    return agent_reply(agent, name, text, ["Reply here to talk to it.", f"`stop {name}` to stop it."])


def working_ack(agent: str, name: str, text: str) -> str:
    return agent_reply(agent, name, text, [f"`status {name}` to see what it is doing.", f"`stop {name}` to stop it."])


def agent_stopped(agent: str, name: str) -> str:
    return agent_reply(agent, name, "Stopped.", ["Send a message to start it again.", "`list` to see what is running."])


def agent_exited(agent: str, name: str) -> str:
    return agent_reply(agent, name, "The agent process exited.", ["Send a message to start a new session."])


def _lead(body: str) -> str:
    """The agent's first sentence, at most LEAD_MAX_CHARS, cut at a word boundary."""
    first = re.split(r"(?<=[.?!])\s|\n", body.strip(), maxsplit=1)[0]
    if len(first) <= LEAD_MAX_CHARS:
        return first
    return first[:LEAD_MAX_CHARS].rsplit(" ", 1)[0]


def _first_part(body: str) -> str:
    """Up to REPLY_MAX_CHARS of body, cut at a paragraph or line boundary in the last half of
    the window, else at any whitespace, never inside a word."""
    window = body[:REPLY_MAX_CHARS]
    for floor in (REPLY_MAX_CHARS // 2, 1):
        for boundary in ("\n\n", "\n", " "):
            cut = window.rfind(boundary)
            if cut >= floor:
                return window[:cut].rstrip()
    return window


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


def agent_result(agent: str, project: str, headline: str, text: str, waiting: bool = False) -> str:
    """A turn's outcome: the headline, then the agent's words on the next line. Over
    REPLY_MAX_CHARS the headline carries a one-sentence lead and the reply ends with a
    trim line, all in one message. Every reply ends with what the user can do next."""
    prefix = f"{SYSTEM_PREFIX} - {agent} - {project}]"
    body = text.strip()
    open_tab = f"Open the {agent} tab in AI Gator"
    answer = "Type your answer."
    keep_going = "Reply here to keep going in this session."
    if not body:
        options = [f"{open_tab} to see it.", answer if waiting else keep_going]
        return f"{prefix} {headline} No text came back.\n\n{next_block(options)}"
    if len(body) <= REPLY_MAX_CHARS:
        if waiting:
            choices = _choices(body)
            options = (
                [*(f"`{c}`" for c in choices), "Or type your own answer."]
                if choices
                else [answer, f"`stop {project}` to stop it instead."]
            )
        else:
            options = [keep_going, "`list` to see all sessions.", "`bye` to close this chat."]
        return f"{prefix} {headline}\n{body}\n\n{next_block(options)}"
    shown = _first_part(body)
    more = len(body) - len(shown)
    if shown.count("```") % 2:
        shown += "\n```"
    options = [f"{open_tab} for the full reply.", answer if waiting else "Reply here to keep going."]
    return f"{prefix} {headline} {_lead(body)}\n\n{shown}\n\nTrimmed, {more} more characters.\n\n{next_block(options)}"
