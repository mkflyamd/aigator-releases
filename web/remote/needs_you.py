"""Which waiting sessions get a chat message now, and which are only named in the summary line."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Callable

if TYPE_CHECKING:
    from remote.service import Session

MAX_MESSAGES = 3
ASK_AFTER_SECONDS = 120.0


@dataclass(frozen=True)
class Plan:
    send: list[Session]
    rest: list[Session]


def plan(
    sessions: list[Session], posted: set[tuple[str, str]], since: Callable[[Session], float], now: float
) -> Plan:
    """`posted` is the (session id, prompt id) pairs that already have a message, each of which holds one of
    the MAX_MESSAGES places until it is answered. A session started in chat is sent at once; any other waits
    ASK_AFTER_SECONDS first, so a user at the desk answers in the app and chat stays quiet. Longest wait first."""
    waiting = [s for s in sessions if s.waiting and s.prompt is not None]
    held = sum(1 for s in waiting if (s.id, s.prompt.id) in posted)
    due = sorted(
        (
            s
            for s in waiting
            if (s.id, s.prompt.id) not in posted and (s.from_chat or now - since(s) >= ASK_AFTER_SECONDS)
        ),
        key=since,
    )
    room = max(0, MAX_MESSAGES - held)
    return Plan(due[:room], due[room:])
