"""The @gator command grammar and reply formatting, independent of any channel."""

from __future__ import annotations

import re
from dataclasses import dataclass

TRIGGER_RE = re.compile(r"^\s*@gator(?:\s+(.*))?$", re.IGNORECASE | re.DOTALL)
RESERVED = ("list", "status", "stop", "help")
TEXT_MAX_BYTES = 4096
REPLY_MAX_CHARS = 3500
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
    body = text.strip()
    extra = len(body) - REPLY_MAX_CHARS
    if extra > 0:
        body = f"{body[:REPLY_MAX_CHARS]}(truncated, {extra} more characters)"
    return f"{SYSTEM_PREFIX} - {agent} - {project}] {body}"
