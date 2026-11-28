"""Remote control settings: the limits read fresh each cycle, and the check a save must pass."""

from __future__ import annotations

from config import load_config

SWITCH_KEYS = ("teams_remote_control_enabled", "slack_remote_control_enabled")
DEFAULT_PROJECT_KEY = "remote_default_project"
AGENT_NAME_KEY = "remote_agent_name"
DEFAULT_AGENT_NAME = "Gator"
AGENT_NAME_MAX_CHARS = 20

# key -> (default, minimum, maximum, label, seconds per unit)
LIMITS = {
    "remote_session_idle_hours": (8.0, 1.0, 72.0, "Session idle limit (hours)", 3600.0),
    "remote_stale_minutes": (15.0, 1.0, 120.0, "Stale message limit (minutes)", 60.0),
    "remote_armed_max_hours": (24.0, 1.0, 168.0, "Remote control time limit (hours)", 3600.0),
}
KEYS = frozenset((*SWITCH_KEYS, DEFAULT_PROJECT_KEY, AGENT_NAME_KEY, *LIMITS))


def _seconds(key: str) -> float:
    default, low, high, _, unit = LIMITS[key]
    value = load_config().get(key)
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not low <= value <= high:
        value = default
    return float(value) * unit


def idle_seconds() -> float:
    return _seconds("remote_session_idle_hours")


def stale_seconds() -> float:
    return _seconds("remote_stale_minutes")


def armed_max_seconds() -> float:
    return _seconds("remote_armed_max_hours")


def valid_agent_name(value: object) -> bool:
    return (
        isinstance(value, str)
        and 1 <= len(value) <= AGENT_NAME_MAX_CHARS
        and not any(ch in value for ch in "[]\r\n")
        and bool(value.strip())
    )


def agent_name() -> str:
    """The name in every chat prefix, `[🐊 {name}]`. Gator unless the setting holds a valid name."""
    value = load_config().get(AGENT_NAME_KEY)
    return value if valid_agent_name(value) else DEFAULT_AGENT_NAME


def validate(body: dict) -> str | None:
    """The reason a save of these settings is refused, or None when it is fine."""
    from skills.code_agent import projects

    for key in SWITCH_KEYS:
        if key in body and not isinstance(body[key], bool):
            return f"{key} must be true or false."
    if DEFAULT_PROJECT_KEY in body:
        name = body[DEFAULT_PROJECT_KEY]
        if name not in (None, ""):
            if not isinstance(name, str) or not (projects.get_project(name) or {}).get("repo_path"):
                return f'There is no project named "{name}". Choose one from the list.'
    if AGENT_NAME_KEY in body and not valid_agent_name(body[AGENT_NAME_KEY]):
        return f"The agent name must be 1 to {AGENT_NAME_MAX_CHARS} characters, with no square brackets or line breaks."
    for key, (_, low, high, label, _unit) in LIMITS.items():
        if key in body:
            value = body[key]
            if isinstance(value, bool) or not isinstance(value, (int, float)) or not low <= value <= high:
                return f"{label} must be a number from {low:g} to {high:g}."
    return None
