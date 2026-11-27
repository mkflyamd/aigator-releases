"""Claude Code terminal agents as relay endpoints (`pty:<terminal id>`).

Finding a session, waking it when suspended, and typing the message into it all stay in
agent_wake; this adapter only translates between that and the relay core."""

from __future__ import annotations

import asyncio

import agent_wake

from .core import DRAFT, Refused
from .model import Endpoint, pty_endpoint

_PERMANENT = {"admin_denied", "switched_off", "opted_out", "invalid"}


def _endpoint(entry: dict) -> Endpoint:
    return pty_endpoint(entry["pty_id"], entry["title"] or entry["session_id"], entry["project_id"])


class TerminalAdapter:
    kind = "pty"

    async def resolve(self, ref: str, sender: Endpoint, *, allow_cross_project: bool) -> list[Endpoint]:
        if ref.startswith("pty:"):
            entry = await asyncio.to_thread(agent_wake.find_by_pty, ref.partition(":")[2])
            found = [entry] if entry and (allow_cross_project or entry["project_id"] == sender.project_id) else []
        else:
            found = await asyncio.to_thread(agent_wake.find_targets, ref, sender.project_id, allow_cross_project)
        return [_endpoint(entry) for entry in found]

    async def deliver(self, sender: Endpoint, target: Endpoint, text: str, mode: str) -> tuple[str, dict]:
        if mode == DRAFT:
            raise Refused("unsupported", "Terminal agents take submitted messages only.")
        entry = await asyncio.to_thread(agent_wake.find_by_pty, target.id.partition(":")[2])
        if entry is None:
            raise Refused("not_found", "That agent is no longer there.")
        who = {"name": sender.name, "session_id": "", "project_id": sender.project_id, "pty_id": sender.id.partition(":")[2]}
        try:
            result = await agent_wake.deliver_entry(who, entry, text, spend_slot=False)
        except agent_wake.WakeRefused as exc:
            raise Refused(exc.code, exc.reason, permanent=exc.code in _PERMANENT, **exc.extra) from exc
        return "submitted", {"woke": result["woke"]}
