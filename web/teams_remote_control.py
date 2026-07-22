"""Teams remote control — relay "/code <command>" self-chat messages into the
active OpenCode terminal session.

Opt-in only (config key "teams_remote_control_enabled", off by default) and
scoped to messages in Teams' "Chat with yourself" thread (chat id "48:notes")
— that's the same trust boundary as anything else done from your own signed-in
Teams account, not an open door for arbitrary senders. A command is only
recognized with an explicit "/code " prefix, so the self-chat stays usable
for ordinary notes-to-self without every line being treated as terminal input.

Deliberately fire-and-forget: no confirmation is ever sent back to Teams —
that would be Gator autonomously sending a Teams message, which CLAUDE.md's
human-in-the-loop rule forbids without explicit approval. The terminal's own
echo of the injected keystrokes is the only feedback, visible next time
Gator's Code tab is open.
"""
from __future__ import annotations

import asyncio
import logging
import re

from config import load_config

_log = logging.getLogger(__name__)

_SELF_CHAT_ID = "48:notes"
_COMMAND_RE = re.compile(r'^\s*/code\s+(.+)$', re.DOTALL)
_POLL_INTERVAL_SECONDS = 8

# In-memory only — deliberately not persisted to disk. On a fresh process
# (restart, or the feature just got toggled on) the first poll baselines to
# "whatever is newest right now" without relaying anything, so a stray old
# message already sitting in the self-chat can never fire retroactively.
_last_seen_message_id: str | None = None
_baselined = False


def _extract_command(body_html: str, body: str) -> str | None:
    """Return the command text if this message matches the "/code <cmd>"
    trigger, else None. Prefers body_html (stripped to plain text) since
    Skype content can carry rich-text markup even for a plainly-typed line;
    falls back to the raw body field for anything body_html didn't cover."""
    from skills._m365.helpers import html_to_text
    text = (html_to_text(body_html).strip() if body_html else "") or (body or "").strip()
    m = _COMMAND_RE.match(text)
    return m.group(1).strip() if m else None


def _fetch_self_chat_messages() -> list[dict]:
    """Blocking: read the self-chat's recent messages via the same Skype
    client the /api/teams/chats/{id}/messages route uses. Newest-first,
    matching that route's own ordering."""
    from routes.teams import _get_skype_module, _get_my_mri, _get_my_name, _normalize_skype_messages
    _rc = _get_skype_module()
    skype_token, messaging_service = _rc.get_auth()
    my_mri = _get_my_mri()
    my_name = _get_my_name()
    raw_msgs, _ = _rc.read_messages(_SELF_CHAT_ID, skype_token, messaging_service, limit=10)
    return _normalize_skype_messages(raw_msgs, my_mri, my_name)


async def _poll_once() -> None:
    global _last_seen_message_id, _baselined
    from skills.code_agent.projects import get_active_pty_session
    from routes.terminal import write_pty_session

    try:
        messages = await asyncio.to_thread(_fetch_self_chat_messages)
    except Exception as exc:
        _log.debug("Teams remote-control poll skipped (fetch failed): %s", exc)
        return

    if not _baselined:
        _baselined = True
        if messages:
            _last_seen_message_id = messages[0].get("id", "")
        return

    if not messages:
        return

    # messages is newest-first. Find where we left off; anything BEFORE that
    # index is newer and unprocessed. If the last-seen id fell out of the
    # fetched window entirely (e.g. a burst of other messages pushed it out),
    # fall back to just the single newest message rather than risking a
    # replay of the whole page.
    try:
        cutoff = next(i for i, m in enumerate(messages) if m.get("id") == _last_seen_message_id)
        new_messages = messages[:cutoff]
    except StopIteration:
        new_messages = messages[:1]

    _last_seen_message_id = messages[0].get("id", _last_seen_message_id)

    for m in reversed(new_messages):  # oldest-of-the-new first, so order is preserved
        if m.get("message_type") != "message":
            continue
        command = _extract_command(m.get("body_html", ""), m.get("body", ""))
        if not command:
            continue
        pty_session_id = get_active_pty_session()
        if not pty_session_id:
            _log.info("Teams remote-control: got %r but no active OpenCode session to target", command)
            continue
        ok = write_pty_session(pty_session_id, command + "\r")
        _log.info("Teams remote-control: relayed %r to session %s (%s)",
                   command, pty_session_id, "delivered" if ok else "session not found")


async def teams_remote_control_loop() -> None:
    """Background loop (started unconditionally from app.py's lifespan, like
    the other periodic loops there) — the config flag is read fresh every
    cycle rather than cached, so toggling it in Settings takes effect on the
    next tick without needing a restart."""
    while True:
        await asyncio.sleep(_POLL_INTERVAL_SECONDS)
        if not load_config().get("teams_remote_control_enabled"):
            continue
        try:
            await _poll_once()
        except Exception as exc:
            _log.warning("Teams remote-control loop failed: %s", exc)
