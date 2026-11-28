"""Agent-reported live state.

A hook inside the agent writes one word (working, asking, idle) to
~/.gator/agent-state/<pty id>; the file's mtime is the event time. Files rather than
a network route: hooks cannot hold a CSRF token, and nothing needs to listen.
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import time
import uuid
from pathlib import Path

STATE_DIR = Path.home() / ".gator" / "agent-state"
HOOKS_DIR = Path.home() / ".gator" / "agent-hooks"
WORDS = ("working", "asking", "idle")
STATE_MAX_AGE_SECONDS = 86400
CRUSH_HOOKS_MIN = (0, 99)

_PTY_FILE = '"$GATOR_AGENT_STATE_DIR/$GATOR_PTY_ID"'
_MODE_FILE = '"$GATOR_AGENT_STATE_DIR/$GATOR_PTY_ID.mode"'
_GUARD = '[ -n "$GATOR_PTY_ID" ] && '
# The hook's stdin is JSON. Only an unescaped key can match, so text a user types
# cannot forge it: inside a JSON string every quote is escaped.
_MODE_CAPTURE = (
    r"""m=$(sed -n 's/.*"permission_mode" *: *"\([A-Za-z]*\)".*/\1/p' | head -n 1); """
)


def _write_cmd(word: str, with_mode: bool = False) -> str:
    cmd = f"printf {word} > {_PTY_FILE}"
    if with_mode:
        cmd = f'{cmd}; {_MODE_CAPTURE}if [ -n "$m" ]; then printf %s "$m" > {_MODE_FILE}; fi'
    return f"{_GUARD}{{ {cmd}; }}" if with_mode else f"{_GUARD}{cmd}"


_REMOVE_CMD = f"{_GUARD}rm -f {_PTY_FILE} {_MODE_FILE}"


def launch_env(pty_id: str) -> dict[str, str]:
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    return {"GATOR_PTY_ID": pty_id, "GATOR_AGENT_STATE_DIR": STATE_DIR.as_posix()}


def _command_hook(command: str, matcher: str | None = None) -> list[dict]:
    group: dict = {"hooks": [{"type": "command", "command": command}]}
    if matcher:
        group["matcher"] = matcher
    return [group]


def _claude_settings() -> dict:
    return {
        "hooks": {
            "UserPromptSubmit": _command_hook(_write_cmd("working", with_mode=True)),
            "PostToolUse": _command_hook(_write_cmd("working")),
            "Notification": _command_hook(_write_cmd("asking"), "permission_prompt|elicitation_dialog"),
            "Stop": _command_hook(_write_cmd("idle", with_mode=True)),
            # A woken agent is ready for a message once it has started; compact and clear
            # also fire SessionStart, and those happen mid-turn.
            "SessionStart": _command_hook(_write_cmd("idle", with_mode=True), "startup|resume"),
            "SessionEnd": _command_hook(_REMOVE_CMD),
        }
    }


def claude_settings_path() -> str:
    """Write the hook settings Claude Code is launched with and return its path."""
    HOOKS_DIR.mkdir(parents=True, exist_ok=True)
    path = HOOKS_DIR / "claude-settings.json"
    body = json.dumps(_claude_settings(), indent=2)
    if not path.exists() or path.read_text(encoding="utf-8") != body:
        path.write_text(body, encoding="utf-8")
    return str(path)


def is_wsl_command(command: list[str] | None) -> bool:
    """WSL does not inherit these variables or the Windows hook shell, so it stays on the output heuristic."""
    return bool(command) and Path(command[0]).stem.lower() == "wsl"


def with_claude_hooks(agent: str, command: list[str] | None) -> list[str] | None:
    if agent != "claude" or not command or is_wsl_command(command):
        return command
    return [*command, "--settings", claude_settings_path()]


_CRUSH_EVENTS = (
    ("TurnStart", "working"),
    ("PermissionRequest", "asking"),
    ("PermissionResult", "working"),
    ("TurnEnd", "idle"),
    ("Interrupt", "idle"),
    ("StopFailure", "idle"),
)


def crush_hook_lines() -> list[str]:
    lines = [
        f'hook add {event} --name "gator-{event.lower()}" --command \'{_write_cmd(word)}\''
        for event, word in _CRUSH_EVENTS
    ]
    lines.append(f'hook add SessionEnd --name "gator-sessionend" --command \'{_REMOVE_CMD}\'')
    return lines


_crush_hooks_cache: dict[str, bool] = {}


def _run_version(exe: str) -> str:
    try:
        out = subprocess.run([exe, "--version"], capture_output=True, text=True, timeout=5)  # noqa: S603
    except (OSError, subprocess.SubprocessError):
        return ""
    return out.stdout or ""


def crush_supports_hooks(exe: str | None) -> bool:
    """Crush gained `hook add` in 0.99; an older crushrc would fail on the unknown command."""
    if not exe:
        return False
    if exe not in _crush_hooks_cache:
        match = re.search(r"(\d+)\.(\d+)", _run_version(exe))
        _crush_hooks_cache[exe] = bool(match) and (int(match[1]), int(match[2])) >= CRUSH_HOOKS_MIN
    return _crush_hooks_cache[exe]


def read_states(pty_ids: list[str]) -> dict[str, dict]:
    out: dict[str, dict] = {}
    for pty in pty_ids:
        try:
            uuid.UUID(pty)
        except ValueError:
            continue
        path = STATE_DIR / pty
        try:
            word = path.read_text(encoding="utf-8").strip().lower()
            at = path.stat().st_mtime
        except OSError:
            continue
        if word in WORDS:
            out[pty] = {"state": word, "at": at}
    return out


def read_mode(pty_id: str) -> str | None:
    """The permission mode the agent last reported (default, plan, acceptEdits,
    bypassPermissions, ...), or None when it has not reported one."""
    try:
        uuid.UUID(pty_id)
        mode = (STATE_DIR / f"{pty_id}.mode").read_text(encoding="utf-8").strip()
    except (ValueError, OSError):
        return None
    return mode if re.fullmatch(r"[A-Za-z]{1,40}", mode) else None


def clear(pty_id: str) -> None:
    """Drop a terminal's reported state, so a reused id does not inherit its last word."""
    try:
        uuid.UUID(pty_id)
        (STATE_DIR / pty_id).unlink(missing_ok=True)
        (STATE_DIR / f"{pty_id}.mode").unlink(missing_ok=True)
    except (ValueError, OSError):
        pass


def cleanup(max_age_seconds: float = STATE_MAX_AGE_SECONDS) -> None:
    cutoff = time.time() - max_age_seconds
    try:
        entries = list(os.scandir(STATE_DIR))
    except OSError:
        return
    for entry in entries:
        try:
            if entry.is_file() and entry.stat().st_mtime < cutoff:
                os.unlink(entry.path)
        except OSError:
            continue
