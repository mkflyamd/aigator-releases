"""Run-on-my-machine routes: the user's Run and Cancel clicks for a run_on_host card.

Both are guarded by verify_csrf (same guard as /api/drafts/{id}/approve), so the
in-process agent loop cannot click Run for the user.
"""
from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from sandbox import host_requests
from sandbox.policy import load_policy
from security import verify_csrf

router = APIRouter()
_log = logging.getLogger(__name__)


class HostShellDecision(BaseModel):
    context_id: str = ""


class HostShellEnabled(BaseModel):
    enabled: bool


def _admin_off() -> bool:
    policy = load_policy()
    return policy.require_sandbox or policy.host_shell == "deny"


def _status() -> dict:
    if _admin_off():
        state = "admin_off"
    else:
        state = "on" if host_requests.user_enabled() else "off"
    return {"state": state, "running": host_requests.running_commands()}


@router.get("/api/host-shell/status")
def host_shell_status():
    return _status()


@router.put("/api/host-shell/enabled", dependencies=[Depends(verify_csrf)])
def set_host_shell_enabled(body: HostShellEnabled):
    """The user's Turn on, or the switch in Settings or the chip. Turning it off also stops running commands."""
    if _admin_off():
        raise HTTPException(status_code=403, detail="Your administrator has turned off running commands on this computer.")
    host_requests.set_user_enabled(body.enabled)
    return {"ok": True, **_status()}


@router.post("/api/host-shell/stop-all", dependencies=[Depends(verify_csrf)])
def stop_all_host_commands():
    host_requests.stop_all()
    return {"ok": True, **_status()}


@router.post("/api/host-shell/{request_id}/run", dependencies=[Depends(verify_csrf)])
def run_host_command(request_id: str, body: HostShellDecision):  # sync: runs in the threadpool while the command executes
    if _admin_off():
        raise HTTPException(status_code=403, detail="Your administrator has turned off running commands on this computer.")
    if not host_requests.user_enabled():
        raise HTTPException(status_code=409, detail="Running commands is turned off. Turn it on, then run the command.")
    try:
        req = host_requests.claim(request_id, body.context_id)
    except host_requests.HostRequestError as exc:
        raise HTTPException(status_code=exc.status_code, detail=str(exc)) from exc
    from skills.shell_runner.tools import run_host_request

    try:
        result = run_host_request(req)
    except Exception as exc:
        result = {"error": f"The command could not be started ({type(exc).__name__}).", "stdout": "", "stderr": "",
                  "exit_code": -1, "ran_on": "host", "cwd": req.cwd}
    if req.stopped:
        result["error"] = "You stopped this command before it finished."
    host_requests.finish(req.id, result)
    # Metadata only: never log the command, folder or output.
    _log.info("host command finished exit_code=%s", result.get("exit_code"))
    return {"ok": True, "request_id": req.id, "result": result}


@router.post("/api/host-shell/{request_id}/cancel", dependencies=[Depends(verify_csrf)])
def cancel_host_command(request_id: str, body: HostShellDecision):
    """Cancel a pending request, or stop a running one by killing its whole process tree. A request that already ended is reported, not an error."""
    try:
        req = host_requests.cancel(request_id, body.context_id)
    except host_requests.HostRequestError as exc:
        raise HTTPException(status_code=exc.status_code, detail=str(exc)) from exc
    return {"ok": True, "request_id": req.id, "status": req.status}
