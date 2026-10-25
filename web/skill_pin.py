"""Per-tab skill pin: validate it and build the context block for the pinned skill."""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Callable

_PROJECT_ID = re.compile(r"^[A-Za-z0-9_.-]{1,80}$")


@dataclass(frozen=True)
class Pin:
    skill: str
    project_id: str | None = None


PIN_CONTEXT_PROVIDERS: dict[str, Callable[[str], str]] = {}


def resolve_pin(pinned_skill, pinned_project_id, known_skills, slash_active: bool = False) -> Pin | None:
    if slash_active or not isinstance(pinned_skill, str) or pinned_skill not in known_skills:
        return None
    valid = isinstance(pinned_project_id, str) and _PROJECT_ID.fullmatch(pinned_project_id)
    return Pin(pinned_skill, pinned_project_id if valid else None)


def pin_context_block(pin: Pin | None) -> str:
    if not pin or not pin.project_id:
        return ""
    provider = PIN_CONTEXT_PROVIDERS.get(pin.skill)
    if not provider:
        return ""
    try:
        text = provider(pin.project_id)
    except Exception:
        return ""
    return f"\n\n{text}" if text else ""


def _demo_recorder_context(project_id: str) -> str:
    import demo_projects as dp

    p = dp.get_project(project_id)
    lines = [
        f"PINNED PROJECT: {p['name']} ({p['project_id']})",
        f"PROJECT_DIR: {p['path']}",
        f"Stage: {p['stage']}",
    ]
    approval = (p.get("ext") or {}).get("approval") or {}
    if approval.get("current_id"):
        lines.append(f"Current narration approval: {approval['current_id']} (version {approval['version']}).")
    lines.append("Use this PROJECT_DIR for every path. Do not look up the active project.")
    return "\n".join(lines)


PIN_CONTEXT_PROVIDERS["gator-demo-recorder"] = _demo_recorder_context
