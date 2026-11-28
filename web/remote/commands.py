"""The @gator command grammar and reply formatting, independent of any channel.

Every message Gator posts follows the copy deck: the prefix and state on line 1, the body, a blank
line, then a `Next:` block of options. Every post opens with the crocodile marker `[🐊`; the loop guard keys on it."""

from __future__ import annotations

import math
import re
from dataclasses import dataclass
from datetime import datetime

from remote import settings

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
TOO_LONG_BODY = "That message is too long to run from this chat, so it was not sent."
TOO_LONG_OPTIONS = ["Start it with `@gator` to send it anyway.", "Or shorten it and send it again."]
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
ACK_DELAY_SECONDS = 15.0
PROGRESS_SECONDS = 120.0
ELAPSED_MIN_SECONDS = 60.0
BREVITY_HINT = "(This session was started from a chat app. Keep replies short, in plain text, with no tables.)"
_CHOICE_RE = re.compile(r"^\s*(?:\d{1,2}|[A-Za-z])[.)]\s+(.+?)\s*$")
LEGACY_OWN_RE = re.compile(r"^\[[^\]\r\n]{0,80}\] " + CROC)
UNKNOWN_MENTION_SHOWN = 3
LEADING_MENTION_RE =re.compile(r"^@([\w.-]+):?(?:\s+(.*))?$", re.DOTALL)


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


def session_list(rows: list[tuple[str, str, str, float, str]]) -> str:
    """rows are (name, project, state, seconds in that state, what to type to answer it). Grouped as the
    History pane groups them, the longest wait first; the project is left out when it is the name."""
    if not rows:
        return no_sessions()
    head = f"{len(rows)} session{'' if len(rows) == 1 else 's'} running:"
    waiting = sorted((r for r in rows if r[2] == WAITING), key=lambda r: -r[3])
    groups = (
        ("Needs you:", waiting),
        ("Working:", [r for r in rows if r[2] == WORKING]),
        ("Idle:", [r for r in rows if r[2] == IDLE]),
    )
    lines, number = [head], 0
    for title, group in groups:
        if group:
            lines.append(title)
        for name, project, state, seconds, _ in group:
            number += 1
            where = "" if _same_name(name, project) else f" {DOT} {project}"
            lead = "waiting " if state == WAITING else ""
            lines.append(f"{number}. {name}{where} {DOT} {lead}{elapsed_words(seconds)}")
    if not waiting:
        return system_reply("\n".join(lines), [])
    name, answer = waiting[0][0], waiting[0][4]
    what = "to allow once." if answer == "allow" else "to answer the longest-waiting one."
    return system_reply("\n".join(lines), [f"`{name}: {answer}` {what}"])


def which_session(names: list[str]) -> str:
    """Several sessions are running and none, or more than one, is waiting: ask which one."""
    options = [f"`{name}: your message`" for name in names[:CHOICES_SHOWN]] + ["`list` to see them all."]
    return system_reply("Which session?", options)


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
    session: str, state: str, since: float, last_activity: float, *, project: str | None = None, several: bool = False
) -> str:
    lead = {WORKING: "Working", WAITING: "Waiting for you", IDLE: "Idle"}[state]
    text = f"{lead} since {clock_time(since)}."
    if clock_time(last_activity) != clock_time(since):
        text += f"\nLast activity {clock_time(last_activity)}."
    return agent_reply(session, text, [], project=project, several=several)


def working_ack(session: str, text: str, *, project: str | None = None, several: bool = False) -> str:
    options = [f"`status {session}` to see what it is doing.", f"`stop {session}` to stop it."]
    return agent_reply(session, text, options, project=project, several=several)


def working(session: str, branch: str | None, several: bool, *, project: str | None = None) -> str:
    """The one message sent when a turn has not finished after ACK_DELAY_SECONDS."""
    body = "Working on it." + (f"\nBranch: {branch}" if branch else "")
    option = f"`stop{f' {session}' if several else ''}` to stop it."
    return agent_reply(session, body, [option], project=project, several=several)


def elapsed_words(seconds: float) -> str:
    """Like 2 min, 12 min or 1 h 5 min: no seconds once past a minute."""
    hours, minutes = divmod(max(1, int(seconds // 60)), 60)
    if hours and minutes:
        return f"{hours} h {minutes} min"
    return f"{hours} h" if hours else f"{minutes} min"


def progress(session: str, elapsed: float, *, project: str | None = None, several: bool = False) -> str:
    return agent_reply(session, f"Still working, {elapsed_words(elapsed)}.", [], project=project, several=several)


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


def agent_exited(session: str, *, project: str | None = None, several: bool = False) -> str:
    return agent_reply(
        session, "The agent process exited.", ["Send a message to start a new session."], project=project, several=several
    )


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


def agent_result(
    agent: str,
    session: str,
    headline: str,
    text: str,
    waiting: bool = False,
    several: bool = False,
    *,
    project: str | None = None,
) -> str:
    """A turn's outcome. An empty headline is a quick answer: the prefix and the agent's words, nothing
    else. Otherwise the headline, then the agent's words on the next line. Over REPLY_MAX_CHARS the
    headline carries a one-sentence lead and the reply ends with a trim line, all in one message. A
    question ends with its choices as options; an empty or trimmed reply ends with what the user can do."""
    prefix = agent_prefix(session, project, several)
    body = _tidy(text)
    open_tab = f"Open the {agent} tab in AI Gator"
    answer = "Type your answer."
    keep_going = "Reply here to keep going in this session."
    if not body:
        options = [f"{open_tab} to see it.", answer if waiting else keep_going]
        return _tidy(f"{prefix} {headline or 'Done.'} No text came back.\n\n{next_block(options)}")
    if len(body) <= REPLY_MAX_CHARS:
        if not headline:
            return _tidy(f"{prefix} {body}")
        if not waiting:
            return _tidy(f"{prefix} {headline}\n{body}")
        tag = f"{session}: " if several else ""
        options = [f"`{tag}{c}`" for c in _choices(body)]
        tail = f"\n\n{next_block(options)}" if options else ""
        return _tidy(f"{prefix} {headline}\n{body}{tail}")
    shown = _first_part(body)
    more = len(body) - len(shown)
    if shown.count("```") % 2:
        shown += "\n```"
    options = [f"{open_tab} for the full reply.", answer if waiting else "Reply here to keep going."]
    return _tidy(
        f"{prefix} {headline or 'Done.'} {_lead(body)}\n\n{shown}\n\nTrimmed, {more} more characters.\n\n{next_block(options)}"
    )
