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
import logging
import time
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

import agent_handoff
import agent_mcp
import agent_sessions
import agent_state
import agent_suspend
import generic_agent
from security import verify_csrf

logger = logging.getLogger(__name__)

router = APIRouter()

_resume_lock = asyncio.Lock()

_INSTALL_HINTS = {
    "codex": "npm install -g @openai/codex",
    "claude": "npm install -g @anthropic-ai/claude-code",
}


def _install_hint_for(agent: str) -> str:
    hint = _INSTALL_HINTS.get(agent)
    return f" ({hint})" if hint else ""


class GenericAgentTerminalRequest(BaseModel):
    agent: str
    project_id: str
    repo_path: str
    force_new: bool = False  # "+" opens another independent process, never reattach
    cols: int = 0  # initial terminal dimensions — sent by the frontend so the
    rows: int = 0  # PTY spawns at the right size before the TUI app paints
    handoff_id: str | None = None  # continue a prior session; always a new process
    resume_id: str | None = None  # reopen a stored session in its own agent; reuses its live terminal if it has one


class HandoffPrepareRequest(BaseModel):
    agent: str
    project_id: str
    repo_path: str
    pty_session_id: str | None = None  # a live terminal...
    session_id: str | None = None  # ...or a stored session from the history panel


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

    A terminal started by remote control is pinned and only detaches here: it
    ends on `@gator stop`, process exit or the remote idle limit, never because
    a Code tab was closed.
    """
    from routes.terminal import HostUnreachable, close_pty_session, session_owner

    try:
        owner = await asyncio.to_thread(session_owner, req.pty_session_id, True)
    except HostUnreachable:
        raise HTTPException(
            status_code=503,
            detail="Could not check whether this terminal is a remote-control session, so it was left open. Try again.",
        ) from None
    if (owner or {}).get("remote_pinned"):
        if generic_agent.get_active_session(req.project_id, req.agent) == req.pty_session_id:
            generic_agent.clear_active_session(req.project_id, req.agent)
        return {"ok": True, "detached": True}

    await asyncio.to_thread(close_pty_session, req.pty_session_id)
    try:
        await asyncio.to_thread(agent_suspend.forget, req.pty_session_id)
    except OSError:
        logger.warning("could not clear the suspended record for %s", req.pty_session_id, exc_info=True)
    generic_agent.unpin_session(req.pty_session_id)
    if generic_agent.get_active_session(req.project_id, req.agent) == req.pty_session_id:
        generic_agent.clear_active_session(req.project_id, req.agent)
    return {"ok": True}


@router.post("/api/generic-agent/handoff/prepare", dependencies=[Depends(verify_csrf)])
async def prepare_agent_handoff(req: HandoffPrepareRequest):
    if not generic_agent.is_supported(req.agent):
        raise HTTPException(status_code=400, detail=f"Unknown agent: {req.agent!r}")
    if bool(req.pty_session_id) == bool(req.session_id):
        raise HTTPException(status_code=400, detail="Give either pty_session_id or session_id.")
    try:
        if req.session_id:
            if req.agent not in ("claude", "codex"):
                raise HTTPException(status_code=400, detail=f"{req.agent!r} has no stored sessions.")
            if not agent_sessions.SESSION_ID_RE.fullmatch(req.session_id):
                raise HTTPException(status_code=400, detail="Invalid session id.")
            stored = await asyncio.to_thread(
                agent_sessions.find_session, req.repo_path, req.agent, req.session_id
            )
            if stored is None:
                raise HTTPException(status_code=404, detail="Session not found in this project.")
            record = await asyncio.to_thread(
                agent_handoff.prepare_handoff_from_transcript,
                req.agent, req.project_id, req.repo_path, Path(stored["path"]),
            )
        else:
            record = await asyncio.to_thread(
                agent_handoff.prepare_handoff,
                req.agent, req.project_id, req.repo_path, req.pty_session_id,
            )
    except agent_handoff.SessionNotOwned:
        raise HTTPException(status_code=403, detail="That terminal session does not belong to this project and agent.")
    except agent_handoff.NothingToHandOff:
        raise HTTPException(status_code=422, detail="Nothing to hand off from this session.")
    except OSError:
        raise HTTPException(status_code=500, detail="The handoff could not be stored securely, so nothing was saved.")
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
    if not req.resume_id:
        return await _open_terminal(req)
    # Serialised so two quick clicks on Resume cannot both find no live terminal and spawn twice.
    async with _resume_lock:
        return await _open_terminal(req)


async def resume_suspended(req: GenericAgentTerminalRequest, pty_id: str, woken_by: str, woken_preview: str = "") -> dict:
    """Resume a suspended session under its old terminal id, so a tab still holding
    that id reattaches. Returns the terminal, or the live one when the session is
    already running."""
    async with _resume_lock:
        return await _open_terminal(req, reuse_pty_id=pty_id, woken_by=woken_by, woken_preview=woken_preview)


async def open_pinned_terminal(req: GenericAgentTerminalRequest, labels: dict[str, str] | None = None) -> dict:
    """A new terminal for remote control: labelled so the idle-suspend sweep never takes it.
    `labels` are kept by the PTY host beside the session, so a restarted backend can find it."""
    return await _open_terminal(req, pinned=True, extra_labels=labels)


async def _open_terminal(
    req: GenericAgentTerminalRequest,
    *,
    reuse_pty_id: str | None = None,
    woken_by: str | None = None,
    woken_preview: str = "",
    pinned: bool = False,
    extra_labels: dict[str, str] | None = None,
):
    """Reattach this project's live session if one exists, else spawn fresh.

    Unlike OpenCode's ensure_instance()+attach split, there's no separate
    server to check readiness on - "does a live PTY already exist for this
    project" is the whole liveness question.

    force_new bypasses reattach entirely (the "+" new-terminal button): each
    generic-agent tab is its own independent process, so a second tab must
    always spawn rather than adopt the first tab's PTY. The last one spawned
    becomes the project's tracked session (what a cold reopen reattaches to).
    """
    from routes.terminal import (
        close_pty_session,
        create_pty_session,
        find_host_session,
        get_pty_session,
        host_session_labels,
    )

    if not generic_agent.is_supported(req.agent):
        raise HTTPException(status_code=400, detail=f"Unknown agent: {req.agent!r}")

    resume = None
    if req.resume_id:
        if req.handoff_id:
            raise HTTPException(status_code=400, detail="A session cannot be resumed and handed off at once.")
        if not generic_agent.can_resume(req.agent):
            raise HTTPException(status_code=400, detail=f"{req.agent!r} cannot resume a session.")
        if not agent_sessions.SESSION_ID_RE.fullmatch(req.resume_id):
            raise HTTPException(status_code=400, detail="Invalid session id.")
        resume = await asyncio.to_thread(agent_sessions.find_session, req.repo_path, req.agent, req.resume_id)
        if resume is None:
            raise HTTPException(status_code=404, detail="Session not found in this project.")
        for live_id in generic_agent.ptys_for_session(req.agent, resume["id"]):
            entry = await asyncio.to_thread(get_pty_session, live_id)
            if entry and not entry.done:
                return {"pty_session_id": live_id, "created": False}

    handoff = None
    if req.handoff_id:
        if not generic_agent.is_handoff_target(req.agent):
            raise HTTPException(status_code=400, detail=f"{req.agent!r} cannot continue a handoff.")
        handoff = await asyncio.to_thread(agent_handoff.load_handoff, req.handoff_id)
        if handoff is None:
            raise HTTPException(status_code=404, detail="Handoff expired or not found.")
    force_new = req.force_new or handoff is not None or resume is not None

    owner = {"project_id": req.project_id, "agent": req.agent}
    if pinned:
        owner["remote_pinned"] = "1"
        owner.update(extra_labels or {})
    if woken_by:
        owner["woken_by"] = woken_by
        owner["woken_preview"] = woken_preview
        owner["woken_at"] = str(int(time.time() * 1000))
    if not force_new:
        existing = generic_agent.get_active_session(req.project_id, req.agent)
        from_host = False
        if not existing:
            # Nothing in memory: either this project never had a terminal, or the
            # backend restarted while the agent kept running in the PTY host.
            # Ask the host, so reopening the project reconnects to that agent
            # instead of starting a second one next to it.
            existing = await asyncio.to_thread(find_host_session, owner)
            from_host = bool(existing)
        if existing:
            entry = await asyncio.to_thread(get_pty_session, existing)
            if entry and not entry.done:
                generic_agent.set_active_session(req.project_id, req.agent, existing)
                if from_host:
                    stored = (await asyncio.to_thread(host_session_labels, existing)).get("session_id")
                    if stored:
                        generic_agent.relink_session(req.agent, existing, stored)
                return {"pty_session_id": existing, "created": False}
            if from_host and entry is None:
                # The agent is (or just was) running but we could not attach.
                # Do not start a duplicate or kill it; the next try can succeed.
                raise HTTPException(
                    status_code=503,
                    detail=(
                        f"Your {req.agent} session is still running but could not "
                        "be reconnected. Try again."
                    ),
                )
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
        command = (
            generic_agent.build_opencode_bare_command(req.repo_path, resume["id"])
            if resume is not None
            else generic_agent.build_opencode_bare_command(req.repo_path)
        )
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
        if resume is not None:
            command = generic_agent.build_resume_command(req.agent, req.repo_path, resume["id"], resume["source"])
        else:
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
                if resume["source"] == "windows" and not generic_agent.find_agent_binary(req.agent):
                    detail = (
                        f"This session was recorded on Windows, but '{req.agent}' is not "
                        f"installed there{_install_hint_for(req.agent)}. Install it and restart AI Gator."
                    )
                else:
                    detail = f"This session cannot be resumed here: '{req.agent}' is not available where it was recorded."
                raise HTTPException(status_code=409, detail=detail)
        else:
            command = generic_agent.build_command(req.agent, req.repo_path, extra)
        if not command:
            hint = _install_hint_for(req.agent)
            raise HTTPException(
                status_code=500,
                detail=(
                    f"'{req.agent}' was not found on PATH. Install it{hint} "
                    "and restart AI Gator."
                ),
            )
        # No gateway config for the profile -> launch on the user's own setup.
        env = generic_agent.with_wsl_env(command, binding[1] if binding else None)

    pty_session_id = reuse_pty_id or generic_agent.new_session_id()
    if reuse_pty_id:
        # Not the last word the old process left: the new one reports its own.
        agent_state.clear(pty_session_id)
    if command:
        if resume is not None:
            command = generic_agent.pin_resume(req.agent, command, pty_session_id, resume["id"])
        else:
            command = generic_agent.pin_session(req.agent, command, pty_session_id)
    if not agent_state.is_wsl_command(command):
        env = {**(env or {}), **agent_state.launch_env(pty_session_id)}
        command = agent_state.with_claude_hooks(req.agent, command)
        env.update(agent_mcp.launch_env(req.agent, command, pty_session_id, req.project_id))
        command = agent_mcp.with_gator_mcp(req.agent, command)
    # Use the frontend's measured dimensions if provided (non-zero), so TUI
    # apps (Crush, Claude Code) spawn at the correct size and don't garble on
    # the late resize. Fall back to create_pty_session's defaults otherwise.
    # Spawning talks to the PTY host over a socket and may start it, so it
    # runs off the event loop.
    size = {"cols": req.cols, "rows": req.rows} if req.cols > 0 and req.rows > 0 else {}
    stored_session = generic_agent.linked_session_id(pty_session_id)
    if stored_session:
        owner = {**owner, "session_id": stored_session}
    spawn_cwd = req.repo_path
    if resume is not None and resume["source"] == "windows" and Path(resume["cwd"]).is_dir():
        spawn_cwd = resume["cwd"]  # a worktree session resumes in its own worktree
    await asyncio.to_thread(
        create_pty_session,
        pty_session_id,
        command=command,
        env=env,
        cwd=spawn_cwd,
        meta=owner,
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
