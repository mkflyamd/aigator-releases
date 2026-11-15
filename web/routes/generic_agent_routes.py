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

import asyncio

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

import agent_handoff
import agent_sessions
import generic_agent
from security import verify_csrf

router = APIRouter()


class GenericAgentTerminalRequest(BaseModel):
    agent: str
    project_id: str
    repo_path: str
    force_new: bool = False  # "+" opens another independent process, never reattach
    cols: int = 0  # initial terminal dimensions — sent by the frontend so the
    rows: int = 0  # PTY spawns at the right size before the TUI app paints
    handoff_id: str | None = None  # continue a prior session; always a new process
    resume_id: str | None = None  # reopen a stored session in its own agent; always a new process


class HandoffPrepareRequest(BaseModel):
    agent: str
    project_id: str
    repo_path: str
    pty_session_id: str


class GenericAgentTerminalCloseRequest(BaseModel):
    agent: str
    project_id: str
    pty_session_id: str


@router.delete("/api/generic-agent/terminal", dependencies=[Depends(verify_csrf)])
async def close_generic_agent_terminal(req: GenericAgentTerminalCloseRequest):
    """Terminate a terminal session explicitly closed by the user.

    Detaching a browser tab is deliberately non-destructive when changing
    projects, but the per-session close button means the user is done with
    this PTY. Remove it from both registries so it cannot reappear on a later
    pane mount.
    """
    from routes.terminal import close_pty_session

    await asyncio.to_thread(close_pty_session, req.pty_session_id)
    generic_agent.unpin_session(req.pty_session_id)
    if generic_agent.get_active_session(req.project_id, req.agent) == req.pty_session_id:
        generic_agent.clear_active_session(req.project_id, req.agent)
    return {"ok": True}


@router.post("/api/generic-agent/handoff/prepare", dependencies=[Depends(verify_csrf)])
async def prepare_agent_handoff(req: HandoffPrepareRequest):
    if not generic_agent.is_supported(req.agent):
        raise HTTPException(status_code=400, detail=f"Unknown agent: {req.agent!r}")
    try:
        record = await asyncio.to_thread(
            agent_handoff.prepare_handoff,
            req.agent, req.project_id, req.repo_path, req.pty_session_id,
        )
    except agent_handoff.NothingToHandOff:
        raise HTTPException(status_code=422, detail="Nothing to hand off from this session.")
    return {
        "handoff_id": record["handoff_id"],
        "source_agent": record["source_agent"],
        "source_kind": record["source_kind"],
        "last_user_message": record["last_user_message"],
        "snapshot_bytes": record["snapshot_bytes"],
        "redactions": record["redactions"],
        "targets": await asyncio.to_thread(generic_agent.handoff_targets),
    }


@router.get("/api/generic-agent/installed")
async def installed_generic_agents():
    agents = generic_agent.launchable_agents()
    found = await asyncio.to_thread(lambda: [generic_agent.is_installed(a) for a in agents])
    installed = dict(zip(agents, found))
    routed = await asyncio.to_thread(
        lambda: {
            a: generic_agent.is_gateway_routed(a)
            for a, ok in installed.items()
            if ok and a != generic_agent.TERMINAL_AGENT
        }
    )
    return {"installed": installed, "gateway_routed": routed}


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

    resume = None
    if req.resume_id:
        if req.handoff_id:
            raise HTTPException(status_code=400, detail="A session cannot be resumed and handed off at once.")
        if req.agent not in ("claude", "codex"):
            raise HTTPException(status_code=400, detail=f"{req.agent!r} cannot resume a session.")
        if not agent_sessions.SESSION_ID_RE.match(req.resume_id):
            raise HTTPException(status_code=400, detail="Invalid session id.")
        resume = await asyncio.to_thread(agent_sessions.find_session, req.repo_path, req.agent, req.resume_id)
        if resume is None:
            raise HTTPException(status_code=404, detail="Session not found in this project.")

    handoff = None
    if req.handoff_id:
        if req.agent == generic_agent.TERMINAL_AGENT:
            raise HTTPException(status_code=400, detail=f"{req.agent!r} cannot continue a handoff.")
        handoff = await asyncio.to_thread(agent_handoff.load_handoff, req.handoff_id)
        if handoff is None:
            raise HTTPException(status_code=404, detail="Handoff expired or not found.")
    force_new = req.force_new or handoff is not None or resume is not None

    if not force_new:
        existing = generic_agent.get_active_session(req.project_id, req.agent)
        if existing:
            entry = await asyncio.to_thread(get_pty_session, existing)
            if entry and not entry.done:
                return {"pty_session_id": existing, "created": False}
            # Stale record (process exited, or the in-memory session dict was
            # cleared by a restart) - drop it and fall through to a fresh spawn.
            # close_pty_session is idempotent even if the process already
            # exited on its own (matches _spawn_attach_pty's cleanup pattern).
            await asyncio.to_thread(close_pty_session, existing)
            generic_agent.clear_active_session(req.project_id, req.agent)

    env = None
    if generic_agent.is_bare_terminal(req.agent):
        command = None  # deliberate - _spawn_pty's bare-shell path, not an error
    elif generic_agent.is_opencode_bare(req.agent):
        command = generic_agent.build_opencode_bare_command(req.repo_path)
        if not command:
            raise HTTPException(
                status_code=500,
                detail=(
                    "'opencode' was not found on PATH. Install it "
                    "(npm install -g opencode-ai) and restart AI Gator."
                ),
            )
        try:
            env = generic_agent.build_opencode_bare_env()
        except RuntimeError as exc:
            raise HTTPException(status_code=500, detail=str(exc))
    elif req.agent == "crush":
        # Crush is PATH-resolved like Claude/Codex, but needs Gator's gateway
        # config injected via a generated crushrc (CRUSH_GLOBAL_CONFIG env) —
        # see generic_agent.build_crush_env. No bundled binary; install via
        # `winget install charmbracelet.crush`.
        command = generic_agent.build_command(req.agent, req.repo_path)
        if not command:
            raise HTTPException(
                status_code=500,
                detail="'crush' was not found on PATH. Install it (winget install charmbracelet.crush) and restart AI Gator.",
            )
        try:
            env = generic_agent.build_crush_env()
        except RuntimeError as exc:
            raise HTTPException(status_code=500, detail=str(exc))
    else:
        binding = generic_agent.effective_binding(req.agent)
        extra = binding[0] if binding else ()
        if resume is not None:
            command = generic_agent.build_resume_command(
                req.agent,
                resume["cwd"] if resume["source"] != "windows" else req.repo_path,
                resume["id"],
                resume["source"],
                extra,
            )
            if not command:
                raise HTTPException(
                    status_code=409,
                    detail=f"This session cannot be resumed here: '{req.agent}' is not available where it was recorded.",
                )
        else:
            command = generic_agent.build_command(req.agent, req.repo_path, extra)
        if not command:
            _install_hint = {
                "codex": "npm install -g @openai/codex",
                "claude": "npm install -g @anthropic-ai/claude-code",
            }.get(req.agent)
            hint = f" ({_install_hint})" if _install_hint else ""
            raise HTTPException(
                status_code=500,
                detail=(
                    f"'{req.agent}' was not found on PATH. Install it{hint} "
                    "and restart AI Gator."
                ),
            )
        # No gateway config for the profile -> launch on the user's own setup.
        env = generic_agent.with_wsl_env(command, binding[1] if binding else None)

    pty_session_id = generic_agent.new_session_id()
    if command:
        if resume is not None:
            command = generic_agent.pin_resume(req.agent, command, pty_session_id, resume["id"])
        else:
            command = generic_agent.pin_session(req.agent, command, pty_session_id)
    # Use the frontend's measured dimensions if provided (non-zero), so TUI
    # apps (Crush, Claude Code) spawn at the correct size and don't garble on
    # the late resize. Fall back to create_pty_session's defaults otherwise.
    # Spawning talks to the PTY host over a socket and may start it, so it
    # runs off the event loop.
    size = {"cols": req.cols, "rows": req.rows} if req.cols > 0 and req.rows > 0 else {}
    await asyncio.to_thread(
        create_pty_session,
        pty_session_id,
        command=command,
        env=env,
        cwd=req.repo_path,
        **size,
    )
    generic_agent.set_active_session(req.project_id, req.agent, pty_session_id)
    result = {"pty_session_id": pty_session_id, "created": True}
    if handoff is not None:
        agent_handoff.log_event(
            "launched",
            project_id=req.project_id,
            source=handoff["source_agent"],
            target=req.agent,
            source_kind=handoff["source_kind"],
            snapshot_bytes=handoff["snapshot_bytes"],
            redactions=handoff["redactions"],
            gateway_routed=agent_handoff.is_gateway_routed(req.agent),
        )
        result["handoff_prompt"] = handoff["prompt"]
    return result
