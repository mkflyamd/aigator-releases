"""Run-on-my-machine routes: the user's Run and Cancel clicks for a run_on_host card, and the card's status poll.

Run and Cancel are guarded by verify_csrf (same guard as /api/drafts/{id}/approve), so the
in-process agent loop cannot click Run for the user. Run returns at once; the Run Supervisor
executes the command and the card follows the run record.
"""
from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

import timeouts
from runs.supervisor import RunError, get_supervisor
from sandbox import host_requests
from sandbox.policy import load_policy
from security import verify_csrf

router = APIRouter()
_log = logging.getLogger(__name__)

_POLICY_BLOCK = "Your administrator has turned off running commands on this computer."
_STOPPED = "You stopped this command before it finished."


class HostShellDecision(BaseModel):
    context_id: str = ""


def _sync_expiry() -> None:
    """The approval registry owns the clock; the supervisor's records follow its expiry events."""
    for request_id in host_requests.expire_due():
        get_supervisor().mark_expired(request_id)


def _http(exc: Exception) -> HTTPException:
    return HTTPException(status_code=exc.status_code, detail=str(exc))


@router.post("/api/host-shell/{request_id}/run", dependencies=[Depends(verify_csrf)])
def run_host_command(request_id: str, body: HostShellDecision):
    _sync_expiry()
    supervisor = get_supervisor()
    policy = load_policy()
    if policy.require_sandbox or policy.host_shell == "deny":
        try:
            supervisor.policy_block(request_id, body.context_id, _POLICY_BLOCK)
            host_requests.deny(request_id, body.context_id)
        except (RunError, host_requests.HostRequestError):
            pass
        raise HTTPException(status_code=403, detail=_POLICY_BLOCK)
    run = supervisor.get(request_id, body.context_id)
    if run is not None and run["state"] in ("preparing", "running"):
        return {"ok": True, "request_id": request_id, "run": run}
    try:
        req = host_requests.claim(request_id, body.context_id)
    except host_requests.HostRequestError as exc:
        if exc.status_code == 410:
            supervisor.mark_expired(request_id)
        raise _http(exc) from exc
    from skills.shell_runner.tools import run_host_request

    def runner(handle):
        result = run_host_request(req, on_start=handle.attach, timeout=handle.timeout_s)
        if handle.cancelled:
            result["error"] = _STOPPED
        return result

    def on_done(result):
        host_requests.finish(req.id, result)
        # Metadata only: never log the command, folder or output.
        _log.info("host command finished exit_code=%s", result.get("exit_code"))

    budgets = timeouts.budgets_for("host", run_ms=req.timeout * 1000)
    try:
        run = supervisor.start(req.id, req.context_id, runner, budgets, on_done)
    except RunError as exc:
        raise _http(exc) from exc
    if run["state"] == "failed_to_start":
        host_requests.finish(req.id, {"error": f"The command did not start: {run['reason']}.", "stdout": "",
                                      "stderr": "", "exit_code": -1, "ran_on": "host", "cwd": req.cwd})
    return {"ok": True, "request_id": req.id, "run": run}


@router.post("/api/host-shell/{request_id}/cancel", dependencies=[Depends(verify_csrf)])
def cancel_host_command(request_id: str, body: HostShellDecision):
    """Cancel a pending request, or stop a running one by killing its whole process tree."""
    _sync_expiry()
    supervisor = get_supervisor()
    try:
        status, _ = host_requests.lookup(request_id, body.context_id)
        if status == "running":
            run = supervisor.cancel(request_id, body.context_id)
        else:
            host_requests.deny(request_id, body.context_id)
            run = supervisor.deny(request_id, body.context_id)
    except (host_requests.HostRequestError, RunError) as exc:
        raise _http(exc) from exc
    return {"ok": True, "request_id": request_id, "status": run["state"], "run": run}


@router.get("/api/host-shell/{request_id}")
def host_command_status(request_id: str, context_id: str = ""):
    """The run record for a card, plus the stored result once the command is over."""
    _sync_expiry()
    run = get_supervisor().get(request_id, context_id)
    if run is None:
        raise HTTPException(status_code=404, detail="This command request was not found or has expired.")
    status, req = host_requests.lookup(request_id, context_id)
    result = req.result if req is not None and status == "done" else None
    return {"ok": True, "request_id": request_id, "run": run, "result": result}


@router.get("/api/runs")
def list_runs(context_id: str = "", limit: int = 20):
    """Recent runs for a tab, newest first, for the status row."""
    _sync_expiry()
    return {"ok": True, "runs": get_supervisor().list(context_id)[: max(1, min(limit, 100))]}
