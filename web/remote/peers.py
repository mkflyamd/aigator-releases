"""Other agent sessions a person can reach from a chat app: who they are, how a typed name picks
one, how often one may be messaged, and the safety checks before text is typed into it.

Reachable means a Claude session in the default project that Remote did not start and that has
not opted out of messages, live or suspended. Delivery goes through the wake-on-ping path
(`agent_wake`), so a suspended session is woken first, nothing is typed at a permission prompt
or while its user is typing, and each delivery is audited."""

from __future__ import annotations

import asyncio
import re
import time
from collections import deque
from dataclasses import dataclass
from typing import Callable, Protocol

from remote.commands import peer_label

READY_SECONDS = 15.0
CACHE_SECONDS = 15.0
WINDOW_SECONDS = 3600.0
SAFE_MODES = frozenset(("default", "plan"))
SCREEN_TAIL_CHARS = 4000
_SKIPS_PROMPTS = re.compile(r"bypass permissions on|accept edits on|auto-accept|auto mode on", re.IGNORECASE)
_ANSI = re.compile(r"\x1b\[[0-?]*[ -/]*[@-~]|\x1b\][^\x07\x1b]*(?:\x07|\x1b\\)|\x1b[@-_]")
_SHORT_CHARS = 8


class PeerRefused(Exception):
    """Nothing was typed. `reason` is safe to show the user."""

    def __init__(self, reason: str, code: str = "refused"):
        super().__init__(reason)
        self.reason = reason
        self.code = code


@dataclass(frozen=True)
class Peer:
    entry: dict

    @property
    def session_id(self) -> str:
        return self.entry["session_id"]

    @property
    def pty_id(self) -> str:
        return self.entry["pty_id"]

    @property
    def state(self) -> str:
        return self.entry["state"]

    @property
    def name(self) -> str:
        return " ".join((self.entry.get("title") or "").split()) or self.session_id

    @property
    def short(self) -> str:
        return self.session_id[:_SHORT_CHARS]


@dataclass(frozen=True)
class Delivery:
    """`pty_id` is the terminal the text was typed into: a woken session has a new one."""

    woke: bool
    pty_id: str


@dataclass(frozen=True)
class Resolved:
    """What a typed name picked: one peer and the message after the name, or several that share it."""

    peer: Peer | None = None
    text: str = ""
    candidates: tuple[Peer, ...] = ()


class PeerGateway(Protocol):
    def entries(self) -> list[dict]: ...
    async def deliver(self, peer: Peer, text: str, sender_name: str) -> Delivery: ...


class WakeGateway:
    """The real thing: `agent_wake` for listing and delivery, `agent_state` for the permission mode."""

    def entries(self) -> list[dict]:
        import agent_wake
        from relay import settings as relay_settings

        return [
            e
            for e in agent_wake.list_entries()
            if not e.get("remote_pinned") and not relay_settings.opted_out(f"pty:{e['pty_id']}")
        ]

    async def deliver(self, peer: Peer, text: str, sender_name: str) -> Delivery:
        """Raises PeerRefused when nothing was typed."""
        import agent_wake

        sender = {"name": sender_name}
        typed_into: list[str] = []

        async def before_type(pty_id: str) -> None:
            typed_into.append(pty_id)
            await self._check_permission_mode(pty_id)

        try:
            result = await agent_wake.deliver_entry(
                sender,
                peer.entry,
                text,
                spend_slot=False,
                origin="user",
                before_type=before_type,
                live_wait=READY_SECONDS,
            )
        except agent_wake.WakeRefused as exc:
            await asyncio.to_thread(agent_wake.audit_refusal, sender, peer.name, exc.code, exc.reason, text)
            raise PeerRefused(exc.reason, exc.code) from exc
        return Delivery(bool(result.get("woke")), typed_into[-1])

    async def _check_permission_mode(self, pty_id: str) -> None:
        """Only a session that asks before it acts is typed into: a person's chat message must not
        be a way past the approval prompts. A mode that cannot be read is treated as unsafe."""
        import agent_wake

        mode = await asyncio.to_thread(_read_mode, pty_id)
        if mode is None:
            raise agent_wake.WakeRefused(
                "unknown_mode",
                "It has not reported its permission mode, so I cannot tell whether it asks before acting.",
            )
        if mode not in SAFE_MODES or await asyncio.to_thread(_screen_skips_prompts, pty_id):
            raise agent_wake.WakeRefused(
                "unsafe_mode", "It is set to run without asking for permission, so I will not message it."
            )


def _read_mode(pty_id: str) -> str | None:
    import agent_state

    return agent_state.read_mode(pty_id)


def _screen_skips_prompts(pty_id: str) -> bool:
    """The mode can change at the keyboard between two hook events, so the footer Claude Code draws
    is read too."""
    from routes import terminal

    entry = terminal.get_pty_session(pty_id)
    if entry is None:
        return False
    _, end = entry.read_from(1 << 60)
    text, _ = entry.read_from(max(0, end - SCREEN_TAIL_CHARS))
    return bool(_SKIPS_PROMPTS.search(_ANSI.sub("", text)))


def addressable(peer: Peer, reserved: frozenset[str]) -> bool:
    """A session whose name starts with a command word or a Remote session's name cannot be picked by
    name without being mistaken for that, so it is reached by its id."""
    title = peer.name
    return title != peer.session_id and title.split()[0].casefold() not in reserved


def resolve(peers: list[Peer], text: str, reserved: frozenset[str], colon_only: bool = False) -> Resolved | None:
    """The peer a message starts with. The name is the whole session name, the session id or its first
    eight characters, matched exactly apart from case, and followed by a space, a colon or the end.
    The longest name wins; two sessions with the same name are returned as candidates. With `colon_only`
    a name counts only when a colon follows it."""
    text = text.strip()
    if text.startswith("@"):
        text = text[1:].lstrip()
    best = 0
    found: dict[str, tuple[Peer, str]] = {}
    for peer in peers:
        names = [peer.session_id, peer.short]
        if addressable(peer, reserved):
            names.append(peer.name)
            if peer_label(peer.name) != peer.name:
                names.append(peer_label(peer.name))
        for name in names:
            n = len(name)
            if n < best or text[:n].casefold() != name.casefold():
                continue
            rest = text[n:]
            if rest and not (rest[0].isspace() or rest[0] == ":"):
                continue
            if colon_only and not rest.startswith(":"):
                continue
            if n > best:
                best, found = n, {}
            found[peer.session_id] = (peer, rest.lstrip(": \t\r\n"))
    if not found:
        return None
    if len(found) > 1:
        return Resolved(candidates=tuple(p for p, _ in found.values()))
    peer, rest = next(iter(found.values()))
    return Resolved(peer=peer, text=rest.strip())


class PeerLimiter:
    """At most `limit()` messages an hour to one peer from this chat. 0 means no limit."""

    def __init__(self, limit: Callable[[], int], clock: Callable[[], float] = time.time):
        self._limit = limit
        self._clock = clock
        self._sent: dict[str, deque[float]] = {}

    def _recent(self, key: str) -> deque[float]:
        stamps = self._sent.setdefault(key, deque())
        now = self._clock()
        while stamps and now - stamps[0] >= WINDOW_SECONDS:
            stamps.popleft()
        return stamps

    def wait_seconds(self, key: str) -> float:
        """0 when a message may be sent now, else how long until one may."""
        limit = self._limit()
        stamps = self._recent(key)
        if limit <= 0 or len(stamps) < limit:
            return 0.0
        return max(1.0, WINDOW_SECONDS - (self._clock() - stamps[0]))

    def record(self, key: str) -> None:
        self._recent(key).append(self._clock())

    @property
    def limit(self) -> int:
        return self._limit()


class PeerDirectory:
    def __init__(
        self,
        gateway: PeerGateway,
        limit: Callable[[], int],
        clock: Callable[[], float] = time.time,
        cache_seconds: float = CACHE_SECONDS,
    ):
        self._gateway = gateway
        self._clock = clock
        self._cache_seconds = cache_seconds
        self._cached: tuple[float, list[dict]] | None = None
        self.limiter = PeerLimiter(limit, clock)

    async def peers(self, project_id: str, exclude_pty: set[str], *, refresh: bool = False) -> list[Peer]:
        """Live ones first, then suspended, each by name. The listing reads session titles from disk,
        so it is reused for a few seconds unless a fresh one is asked for."""
        entries = await self._entries(refresh)
        peers = [Peer(e) for e in entries if e.get("project_id") == project_id and e["pty_id"] not in exclude_pty]
        return sorted(peers, key=lambda p: (p.state != "live", p.name.casefold(), p.session_id))

    async def by_pty(self, pty_id: str) -> Peer | None:
        """The reachable agent running in this terminal, from a fresh listing, whatever its project."""
        return next((Peer(e) for e in await self._entries(True) if e["pty_id"] == pty_id), None)

    async def _entries(self, refresh: bool) -> list[dict]:
        now = self._clock()
        if refresh or self._cached is None or now - self._cached[0] >= self._cache_seconds:
            self._cached = (now, await asyncio.to_thread(self._gateway.entries))
        return self._cached[1]

    async def deliver(self, peer: Peer, text: str, sender_name: str) -> Delivery:
        delivery = await self._gateway.deliver(peer, text, sender_name)
        self.limiter.record(peer.session_id)
        self._cached = None
        return delivery
