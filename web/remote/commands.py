"""The @gator command grammar and reply formatting, independent of any channel."""

from __future__ import annotations

import re
from dataclasses import dataclass

TRIGGER_RE = re.compile(r"^\s*@gator(?:\s+(.*))?$", re.IGNORECASE | re.DOTALL)
RESERVED = ("list", "status", "stop", "help")
TEXT_MAX_BYTES = 4096
REPLY_MAX_CHARS = 3500
LEAD_MAX_CHARS = 200
SYSTEM_PREFIX = "[Gator"


@dataclass(frozen=True)
class Command:
    kind: str  # send | list | status | stop | stop_all | help
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
