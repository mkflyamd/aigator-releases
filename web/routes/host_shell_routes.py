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


@router.post("/api/host-shell/{request_id}/run", dependencies=[Depends(verify_csrf)])
def run_host_command(request_id: str, body: HostShellDecision):  # sync: runs in the threadpool while the command executes
    policy = load_policy()
    if policy.require_sandbox or policy.host_shell == "deny":
        raise HTTPException(status_code=403, detail="Your administrator has turned off running commands on this computer.")
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
    host_requests.finish(req.id, result)
    # Metadata only: never log the command, folder or output.
    _log.info("host command finished exit_code=%s", result.get("exit_code"))
    return {"ok": True, "request_id": req.id, "result": result}


@router.post("/api/host-shell/{request_id}/cancel", dependencies=[Depends(verify_csrf)])
def cancel_host_command(request_id: str, body: HostShellDecision):
    try:
        req = host_requests.deny(request_id, body.context_id)
    except host_requests.HostRequestError as exc:
        raise HTTPException(status_code=exc.status_code, detail=str(exc)) from exc
    return {"ok": True, "request_id": req.id, "status": req.status}
