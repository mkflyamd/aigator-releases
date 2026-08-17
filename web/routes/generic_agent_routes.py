"""Generic terminal-based coding agent routes (Claude Code CLI, Codex CLI,
Crush, ...) — see web/generic_agent.py for the design rationale.

One endpoint, mirroring the shape of /api/opencode/terminal but far simpler:
no server lifecycle, no health check, no config injection (except the
opencode-bare agent — see generic_agent.py's docstring). Reuses the exact
same /api/terminal/agent WebSocket the OpenCode terminal and the manual
terminal panel already use — it just pumps whatever the PTY wraps, and has
never needed to know which of those callers it's serving.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

import generic_agent
from security import verify_csrf

router = APIRouter()


class GenericAgentTerminalRequest(BaseModel):
    agent: str
    project_id: str
    repo_path: str
    force_new: bool = False  # "+" opens another independent process, never reattach


@router.post("/api/generic-agent/terminal", dependencies=[Depends(verify_csrf)])
async def generic_agent_terminal(req: GenericAgentTerminalRequest):
    """Reattach this project's live session if one exists, else spawn fresh.

    Unlike OpenCode's ensure_instance()+attach split, there's no separate
    server to check readiness on - "does a live PTY already exist for this
    project" is the whole liveness question.

    force_new bypasses reattach entirely (the "+" new-terminal button): each
    generic-agent tab is its own independent process, so a second tab must
    always spawn rather than adopt the first tab's PTY. The last one spawned
    becomes the project's tracked session (what a cold reopen reattaches to).
    """
    from routes.terminal import create_pty_session, get_pty_session, close_pty_session

    if not generic_agent.is_supported(req.agent):
        raise HTTPException(status_code=400, detail=f"Unknown agent: {req.agent!r}")

    if not req.force_new:
        existing = generic_agent.get_active_session(req.project_id, req.agent)
        if existing:
            entry = get_pty_session(existing)
            if entry and not entry["done"]:
                return {"pty_session_id": existing, "created": False}
            # Stale record (process exited, or the in-memory session dict was
            # cleared by a restart) - drop it and fall through to a fresh spawn.
            # close_pty_session is idempotent even if the process already
            # exited on its own (matches _spawn_attach_pty's cleanup pattern).
            close_pty_session(existing)
            generic_agent.clear_active_session(req.project_id, req.agent)

    env = None
    if generic_agent.is_bare_terminal(req.agent):
        command = None  # deliberate - _spawn_pty's bare-shell path, not an error
    elif generic_agent.is_opencode_bare(req.agent):
        command = generic_agent.build_opencode_bare_command(req.repo_path)
        if not command:
            raise HTTPException(
                status_code=500,
                detail="OpenCode binary not found. Reinstall AI Gator to restore it.",
            )
        try:
            env = generic_agent.build_opencode_bare_env()
        except RuntimeError as exc:
            raise HTTPException(status_code=500, detail=str(exc))
    else:
        command = generic_agent.build_command(req.agent)
        if not command:
            raise HTTPException(
                status_code=500,
                detail=f"'{req.agent}' was not found on PATH. Install it and restart AI Gator.",
            )

    pty_session_id = generic_agent.new_session_id()
    create_pty_session(pty_session_id, command=command, env=env, cwd=req.repo_path)
    generic_agent.set_active_session(req.project_id, req.agent, pty_session_id)
    return {"pty_session_id": pty_session_id, "created": True}
