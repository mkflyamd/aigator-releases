"""Generic terminal-based coding agents (Claude Code CLI, Codex CLI, Crush,
...) — an alternative to OpenCode for users who already have one of these
installed and configured with their own provider/API keys.

Deliberately the opposite of instance_manager.py's OpenCode integration:
- No bundled binary, no self-heal, no version pinning — BYO install, resolved
  via PATH (shutil.which) same as running it in a normal terminal.
- No server/health-check lifecycle — these are single foreground processes
  per session, not a `serve` + `attach` split like OpenCode.
- No config injection — the tool reads its own native config exactly as it
  would outside Gator. Gator only decides WHICH command to spawn and WHERE
  (repo_path as cwd); everything else is the tool's own business.

This intentionally does not share code with instance_manager.py/
opencode_routes.py — OpenCode's path is deliberately left untouched to avoid
any regression risk to it while this is being built out.
"""
from __future__ import annotations

import shutil
import uuid

# name -> argv. Extend here to add a new agent; no other file needs to know
# the executable name. Values are lists (not a bare string) so a future entry
# needing fixed flags (e.g. a non-interactive/resume flag) can just add them.
SUPPORTED_AGENTS: dict[str, list[str]] = {
    "claude": ["claude"],
    "codex": ["codex"],
    "crush": ["crush"],
}

# A bare shell in the project directory - the maximally-flexible fallback for
# a tool not in SUPPORTED_AGENTS (or no tool at all), rather than maintaining
# an ever-growing fixed list. Not in SUPPORTED_AGENTS since it needs no
# binary resolution at all - it's just create_pty_session(command=None) with
# cwd set to the project, identical to what the general terminal.js panel
# already spawns, just scoped to a specific repo instead of Gator's own cwd.
TERMINAL_AGENT = "terminal"


def is_supported(agent: str) -> bool:
    return agent in SUPPORTED_AGENTS or agent == TERMINAL_AGENT


def is_bare_terminal(agent: str) -> bool:
    return agent == TERMINAL_AGENT


def find_agent_binary(agent: str) -> str | None:
    """Resolve the agent's binary on PATH. None if not installed - the route
    layer turns this into a clear "not installed" error rather than a
    confusing PTY that dies instantly."""
    argv = SUPPORTED_AGENTS.get(agent)
    if not argv:
        return None
    return shutil.which(argv[0])


def build_command(agent: str) -> list[str] | None:
    """Full argv to spawn for this agent, with the resolved absolute binary
    path in place of the bare name (matches OpenCode's own build_opencode_
    command pattern of never relying on child-process PATH resolution)."""
    argv = SUPPORTED_AGENTS.get(agent)
    if not argv:
        return None
    resolved = find_agent_binary(agent)
    if not resolved:
        return None
    return [resolved, *argv[1:]]


# (project_id, agent) -> pty_session_id of that project+agent's current
# terminal. In-memory only (unlike OpenCode's disk-backed instance registry) —
# a server restart just means "no known session to resume", which for a
# single-foreground-process tool with no server-side state to reconnect to is
# a reasonable v1 tradeoff, not a regression against anything that exists
# today.
#
# Real bug found via user report: this was keyed by project_id ALONE. A
# project switched from Claude to Terminal (or vice versa) would still find
# the OTHER agent's still-alive session under that same project_id key and
# silently reattach to it - "Start Claude" would hand back a live PowerShell
# PTY, or switching away from Claude to anything else would just reload
# Claude again, regardless of what was actually requested. The agent must be
# part of the identity of "this project's active session", not just the
# project - each agent has its own independent process per project.
_active_sessions: dict[tuple[str, str], str] = {}


def get_active_session(project_id: str, agent: str) -> str | None:
    return _active_sessions.get((project_id, agent))


def set_active_session(project_id: str, agent: str, pty_session_id: str) -> None:
    _active_sessions[(project_id, agent)] = pty_session_id


def clear_active_session(project_id: str, agent: str) -> None:
    _active_sessions.pop((project_id, agent), None)


def new_session_id() -> str:
    return str(uuid.uuid4())
