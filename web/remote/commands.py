"""The @gator command grammar and reply formatting, independent of any channel."""

from __future__ import annotations

import math
import re
from dataclasses import dataclass

TRIGGER_RE = re.compile(r"^\s*@gator(?:\s+(.*))?$", re.IGNORECASE | re.DOTALL)
GREETING_WORDS = ("hi", "hello", "hey", "start")
RESERVED = ("list", "status", "stop", "help", "bye", *GREETING_WORDS)
WINDOW_SECONDS = 30 * 60.0
NAME_MAX_CHARS = 40
TEXT_MAX_BYTES = 4096
REPLY_MAX_CHARS = 3500
LEAD_MAX_CHARS = 200
SYSTEM_PREFIX = "[Gator"
SETTINGS_SECTION = "Remote control"


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


def system_reply(text: str) -> str:
    return f"{SYSTEM_PREFIX}] {text}"


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


def _tips() -> str:
    return (
        "Type a request and it runs in your Claude session.\n"
        "`list` \u00b7 `status [name]` \u00b7 `stop [name]` \u00b7 `stop all`\n"
        "`bye` closes the chat. `help` shows this again.\n"
        f"It also closes after {in_words(WINDOW_SECONDS)} of quiet."
    )


def greeting() -> str:
    return system_reply(f"Gator on watch. This chat is open, so you can skip `@gator`.\n{_tips()}")


def help_text() -> str:
    return system_reply(_tips())


def chat_closed_quiet() -> str:
    return system_reply(f"Chat closed after {in_words(WINDOW_SECONDS)} of quiet. Send `@gator hi` to open it again.")


def chat_closed_bye() -> str:
    return system_reply("Chat closed. Gator out. Send `@gator hi` to open it again.")


def timed_out(seconds: float) -> str:
    return system_reply(
        f"Remote control turned itself off after {in_words(seconds)}. "
        f"Turn it back on in AI Gator settings, under {SETTINGS_SECTION}."
    )


def slow_down(wait_seconds: float) -> str:
    return system_reply(f"Slow down, that was too many messages at once. Try again in {in_words(wait_seconds)}.")


def stale_skipped(count: int, limit_seconds: float) -> str:
    what = "a message" if count == 1 else f"{count} messages"
    return system_reply(
        f"Skipped {what} you sent while AI Gator was off, because it was more than {in_words(limit_seconds)} old. "
        "Send it again if you still need it."
    )


def stopped(count: int) -> str:
    return system_reply(f"Stopped {count} session{'' if count == 1 else 's'}.")


def no_sessions() -> str:
    return system_reply("No remote sessions are running.")


def not_found_text(name: str) -> str:
    """The user-typed name is echoed back, so it is flattened to one line and capped."""
    shown = " ".join(name.split())[:NAME_MAX_CHARS]
    return f"No session named {shown}. Send `list` to see what is running."


def session_not_found(name: str) -> str:
    return system_reply(not_found_text(name))


def session_list(rows: list[tuple[str, str, str]]) -> str:
    """rows are (name, project, state); state is one of working, waiting for you, idle."""
    if not rows:
        return no_sessions()
    head = f"{len(rows)} session{'' if len(rows) == 1 else 's'} running:"
    lines = [f"{i}. {name} \u00b7 {project} \u00b7 {state}" for i, (name, project, state) in enumerate(rows, 1)]
    return system_reply("\n".join([head, *lines]))


def agent_reply(agent: str, project: str, text: str) -> str:
    return f"{SYSTEM_PREFIX} - {agent} - {project}] {text.strip()}"


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


def agent_result(agent: str, project: str, headline: str, text: str) -> str:
    """A turn's outcome: the headline, then the agent's words on the next line. Over
    REPLY_MAX_CHARS the headline carries a one-sentence lead and the reply ends with a
    trim line, all in one message."""
    prefix = f"{SYSTEM_PREFIX} - {agent} - {project}]"
    body = text.strip()
    if not body:
        return f"{prefix} {headline} No text came back. Open the {agent} tab in AI Gator."
    if len(body) <= REPLY_MAX_CHARS:
        return f"{prefix} {headline}\n{body}"
    shown = _first_part(body)
    more = len(body) - len(shown)
    if shown.count("```") % 2:
        shown += "\n```"
    return (
        f"{prefix} {headline} {_lead(body)}\n\n{shown}\n\n"
        f"Trimmed, {more} more characters. Open the {agent} tab in AI Gator for the full reply."
    )
