"""OpenCode dispatcher routes — see docs/internal/OpenCodeIntegrationPlan.md §5.

Three endpoints:
  POST /api/opencode/warm — fire-and-forget: spawn (or confirm running) the
    server for a project with no session/terminal side effects, so a later
    real dispatch/terminal call can skip the cold-start wait.
  POST /api/opencode/terminal — spawn a PTY running `opencode attach`, for
    a session the caller already knows the id of (built first, still used
    standalone for the tab-reattach-on-return case where the frontend
    already has a pty_session_id or opencode session_id in hand).
  POST /api/opencode/dispatch — the actual dispatcher: seed a starting task
    into a session (creating one if the tab doesn't have one bound yet),
    then spawn+return the attach terminal in one call. This is what a
    "fix this GitHub issue" / pinned-item-handoff trigger calls.
"""
from __future__ import annotations

import asyncio
import threading
import uuid

import httpx
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from security import verify_csrf
from skills.opencode_agent import instance_manager

router = APIRouter()

# OpenCode session id -> pty_session_id of that session's CURRENT attach
# terminal. Every /terminal and /dispatch call spawns a fresh `opencode
# attach` process; a reattach/redispatch for a session that already had one
# used to just spawn another and orphan the old, leaking attach processes
# (dozens observed for a single session, each holding a pooled read thread -
# a primary cause of the thread-pool exhaustion that hung the app). Tracking
# the current attach per session lets a new spawn reap the previous first, so
# there's at most one live attach per session. Guarded by a lock because
# _spawn_attach_pty runs on a worker thread (see _run_opencode).
_attach_by_session: dict[str, str] = {}
_attach_lock = threading.Lock()


async def _run_opencode(fn, *args):
    """Run a blocking OpenCode operation (cold `ensure_instance` spawn, PTY
    spawn) on the dedicated OpenCode thread pool rather than asyncio's shared
    default executor. A cold spawn parks a worker for ~15-20s; on the default
    pool that starved unrelated endpoints (git/status, LLM calls) and helped
    hang the whole app. See terminal.OPENCODE_POOL for the full rationale -
    reusing that same pool keeps every OpenCode blocking op under one ceiling.
    """
    from routes.terminal import OPENCODE_POOL
    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(OPENCODE_POOL, fn, *args)


class AttachTerminalRequest(BaseModel):
    project_id: str
    repo_path: str
    session_id: str  # the OpenCode session id to attach to


def _spawn_attach_pty(inst: instance_manager.OpencodeServerInstance, session_id: str) -> str:
    """Spawn a PTY running `opencode attach` for a given instance+session.
    Shared by /terminal and /dispatch so the command-building logic lives
    in exactly one place.
    """
    from routes.terminal import create_pty_session, close_pty_session

    opencode_bin = instance_manager.find_bundled_opencode()
    if not opencode_bin:
        raise HTTPException(status_code=500, detail="OpenCode binary not found.")

    attach_cmd = instance_manager.build_opencode_command(
        opencode_bin,
        ["attach", f"http://127.0.0.1:{inst.port}", "--session", session_id],
    )
    with _attach_lock:
        # Reap this session's previous attach (if any) before spawning its
        # replacement - otherwise repeated reattach/dispatch pile up duplicate
        # `opencode attach` processes for one session, each squatting a read
        # thread. One live attach per session. close_pty_session is a no-op if
        # the old one is already gone.
        old_pty = _attach_by_session.get(session_id)
        if old_pty:
            close_pty_session(old_pty)
        pty_session_id = str(uuid.uuid4())
        create_pty_session(pty_session_id, command=attach_cmd, env={"OPENCODE_SERVER_PASSWORD": inst.password})
        _attach_by_session[session_id] = pty_session_id
    return pty_session_id


class WarmRequest(BaseModel):
    project_id: str
    repo_path: str


class ActivePtySessionRequest(BaseModel):
    pty_session_id: str


@router.put("/api/opencode/active-pty-session", dependencies=[Depends(verify_csrf)])
async def set_active_pty_session(req: ActivePtySessionRequest):
    """Record the most recently activated terminal session, fire-and-forget
    from the frontend on every session activation.

    Lets a purely backend-triggered event (Teams remote control, see
    web/teams_remote_control.py) know which live PTY to target without a
    connected browser tab to ask - the frontend's own _ocTerminals tracking
    is browser-tab-scoped and invisible to the backend otherwise.
    """
    from skills.code_agent.projects import set_active_pty_session
    set_active_pty_session(req.pty_session_id)
    return {"ok": True}


@router.post("/api/opencode/warm", dependencies=[Depends(verify_csrf)])
async def warm(req: WarmRequest):
    """Spawn (or confirm running) the OpenCode server for a project without
    creating a session or attaching a terminal - fire-and-forget from the
    frontend as soon as the project list loads, for whichever project the
    server remembers as "active" (the user's likely next pick). Real latency
    found via user report: cold-starting `opencode serve` takes several
    seconds (subprocess spawn + readiness poll in instance_manager.py); by
    the time the user actually clicks that project, ensure_instance() below
    may already find it running and return near-instantly instead.
    """
    try:
        # Threaded, not called directly: a cold ensure_instance() blocks on
        # subprocess spawn + a polling readiness wait (up to 15s,
        # instance_manager._wait_until_ready) - called synchronously inside
        # this async route, that would freeze FastAPI's single event loop for
        # the whole app, not just this request, for as long as the wait runs.
        inst = await _run_opencode(instance_manager.ensure_instance, req.project_id, req.repo_path)
    except RuntimeError as exc:
        raise HTTPException(status_code=500, detail=str(exc))
    return {"status": inst.status}


@router.get("/api/opencode/mcp_status")
async def mcp_status(project_id: str):
    """Query the running instance's MCP connection status (GET /mcp on the
    opencode server itself - see instance_manager.get_mcp_status). Called by
    the frontend once, shortly after a session's terminal connects, to catch
    a real gap: a manually-edited MCP config has no effect on an
    already-running server (it only reads MCP config at startup), so a user
    could be running with a silently-failed MCP with no signal anywhere
    except OpenCode's own logs. Returns {} (not an error) if no instance is
    running or the probe fails - the frontend treats that as "unknown/skip",
    not "something failed".
    """
    inst = instance_manager.get_instance(project_id)
    if not inst or inst.status != "running" or not inst.password:
        return {}
    status = await _run_opencode(instance_manager.get_mcp_status, inst.port, inst.password)
    return status


class RestartRequest(BaseModel):
    project_id: str
    repo_path: str


@router.post("/api/opencode/restart", dependencies=[Depends(verify_csrf)])
async def restart(req: RestartRequest):
    """Force-restart this project's OpenCode server (see
    instance_manager.force_restart_instance) - unlike ensure_instance()'s
    adopt-instead-of-kill, this unconditionally kills and respawns, so every
    config layer gets re-read fresh. User-triggered escape hatch for "this
    session's MCP config is stale" (surfaced via the mcp_status check above),
    distinct from the crash-recovery restart which never touches a live
    process because there isn't one to touch.
    """
    try:
        inst = await _run_opencode(instance_manager.force_restart_instance, req.project_id, req.repo_path)
    except RuntimeError as exc:
        raise HTTPException(status_code=500, detail=str(exc))
    if inst.status != "running":
        raise HTTPException(status_code=500, detail="OpenCode server did not start correctly.")
    return {"status": inst.status}


@router.post("/api/opencode/terminal", dependencies=[Depends(verify_csrf)])
async def attach_terminal(req: AttachTerminalRequest):
    """Spawn a PTY running `opencode attach` for the middle-pane terminal.

    Returns a pty_session_id the frontend connects to via the existing
    /api/terminal/agent WebSocket - the same named-session reconnect/replay
    infrastructure already built for the native coding-agent engine, reused
    as-is since it's already process-agnostic (it just pumps whatever the
    PTY object wraps).
    """
    try:
        # See warm()'s comment - threaded so a cold spawn doesn't block the
        # whole app's event loop.
        inst = await _run_opencode(instance_manager.ensure_instance, req.project_id, req.repo_path)
    except RuntimeError as exc:
        raise HTTPException(status_code=500, detail=str(exc))

    if inst.status != "running":
        raise HTTPException(status_code=500, detail="OpenCode server did not start correctly.")

    # PTY spawn is also a blocking subprocess call (routes/terminal.py's
    # create_pty_session - direct PtyProcess.spawn/subprocess.Popen, not
    # threaded internally) - thread it too rather than block the event loop.
    pty_session_id = await _run_opencode(_spawn_attach_pty, inst, req.session_id)
    return {"pty_session_id": pty_session_id}


class DispatchRequest(BaseModel):
    project_id: str
    repo_path: str
    session_id: str | None = None  # existing session to seed, or None to create fresh
    # Optional: the starting task (issue/ticket text, pinned item content).
    # None means "just start a bare session" - e.g. selecting a project in
    # the Code tab with nothing specific to work on yet; the user then
    # types directly into the attached terminal.
    context_text: str | None = None


@router.post("/api/opencode/dispatch", dependencies=[Depends(verify_csrf)])
async def dispatch(req: DispatchRequest):
    """Create/reattach an OpenCode session and attach a terminal to it, in
    one call. This is the entry point both for "fix this GitHub issue" (with
    context_text) and for simply selecting a project in the Code tab with
    nothing specific yet (context_text omitted - just starts a bare session).

    Two paths, matching the flows in OpenCodeIntegrationPlan.md §5.5:
    - session_id given (the active tab already has one bound): verify it
      still exists, then POST the new context to it directly - proven live
      propagation to an already-open/attached session.
    - session_id is None, or the given one turns out to be gone: create a
      fresh session and seed it - the "auto-start with that context"
      fallback, used identically whether this is a brand-new task or a
      pinned-item handoff onto a tab with no session yet.
    """
    try:
        # See warm()'s comment - threaded so a cold spawn doesn't block the
        # whole app's event loop.
        inst = await _run_opencode(instance_manager.ensure_instance, req.project_id, req.repo_path)
    except RuntimeError as exc:
        raise HTTPException(status_code=500, detail=str(exc))
    if inst.status != "running":
        raise HTTPException(status_code=500, detail="OpenCode server did not start correctly.")

    base_url = f"http://127.0.0.1:{inst.port}"
    auth = ("opencode", inst.password)

    # Two different timeout needs, not one: the session-existence check and
    # session-create are quick, metadata-only calls, but the message POST
    # triggers a real LLM completion - found via a real ReadTimeout in
    # production logs, not assumed: a normal, successful response has
    # already been observed taking 19.2s in this same testing session, well
    # past a 15s client-wide timeout that was originally set for all three
    # calls uniformly. Per-request override, not a blanket client timeout.
    # Whether THIS call created a brand-new OpenCode session (vs reattaching to
    # one the caller already had). The frontend uses it to auto-collapse
    # OpenCode's TUI sidebar exactly once on a fresh session - doing it on a
    # reattach would toggle the sidebar back ON, since it's a stateful toggle.
    created = False
    async with httpx.AsyncClient(timeout=15, auth=auth) as client:
        session_id = req.session_id
        if session_id:
            # A bogus/gone session id doesn't reliably 404 - OpenCode returns
            # a generic 500 for an unknown id (confirmed via direct testing,
            # not assumed) - so treat any non-200 as "doesn't exist anymore".
            check = await client.get(f"{base_url}/session/{session_id}")
            if check.status_code != 200:
                session_id = None

        if not session_id:
            create_resp = await client.post(f"{base_url}/session", json={})
            if create_resp.status_code != 200:
                raise HTTPException(status_code=502, detail="OpenCode server rejected session creation.")
            session_id = create_resp.json()["id"]
            created = True

        # No explicit model field - confirmed via direct testing that the
        # message endpoint falls back to the project's config default
        # (instance_manager._build_provider_config's "model" key) when omitted,
        # so this respects whatever model the user has set for the project.
        # 120s, not the client's 15s default - this call waits for a real LLM
        # completion, not a metadata lookup.
        if not req.context_text:
            pty_session_id = await _run_opencode(_spawn_attach_pty, inst, session_id)
            return {"session_id": session_id, "pty_session_id": pty_session_id, "created": created}

        try:
            msg_resp = await client.post(
                f"{base_url}/session/{session_id}/message",
                json={"parts": [{"type": "text", "text": req.context_text}]},
                timeout=120,
            )
        except httpx.ReadTimeout:
            raise HTTPException(
                status_code=504,
                detail="OpenCode is taking longer than expected to respond. The session was created "
                       "and the terminal can still be attached - check it directly.",
            )
        if msg_resp.status_code != 200:
            raise HTTPException(status_code=502, detail="OpenCode server rejected the seeded message.")

    pty_session_id = await _run_opencode(_spawn_attach_pty, inst, session_id)
    return {"session_id": session_id, "pty_session_id": pty_session_id, "created": created}
