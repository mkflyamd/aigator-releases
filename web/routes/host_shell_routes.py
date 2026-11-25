"""Run-on-my-machine routes: the user's Run and Cancel clicks for a run_on_host card, and the card's status poll.

Run and Cancel are guarded by verify_csrf (same guard as /api/drafts/{id}/approve), so the
in-process agent loop cannot click Run for the user. Run returns at once; the Run Supervisor
executes the command and the card follows the run record.
"""
from __future__ import annotations

import logging
import threading
from contextlib import contextmanager

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


_STARTED = ("preparing", "running", "finished", "timed_out", "cancelled", "failed_to_start", "interrupted")
_GUARDS: dict[str, list] = {}
_GUARDS_LOCK = threading.Lock()


@contextmanager
def _one_at_a_time(request_id: str):
    """Run and Cancel for one request take turns, so a double-click or a Stop racing a Run sees a settled record."""
    with _GUARDS_LOCK:
        guard = _GUARDS.setdefault(request_id, [threading.Lock(), 0])
        guard[1] += 1
    try:
        with guard[0]:
            yield
    finally:
        with _GUARDS_LOCK:
            guard[1] -= 1
            if guard[1] == 0:
                _GUARDS.pop(request_id, None)


def _http(exc: Exception) -> HTTPException:
    return HTTPException(status_code=exc.status_code, detail=str(exc))


@router.post("/api/host-shell/{request_id}/run", dependencies=[Depends(verify_csrf)])
def run_host_command(request_id: str, body: HostShellDecision):
    with _one_at_a_time(request_id):
        return _run_locked(request_id, body)


def _run_locked(request_id: str, body: HostShellDecision):
    host_requests.sync_expiry()
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
    if run is not None and run["state"] in _STARTED:
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
        _not_started(req, str(exc))
        raise _http(exc) from exc
    except Exception as exc:
        _log.warning("host command could not be started (%s)", type(exc).__name__)
        _not_started(req, type(exc).__name__)
        raise HTTPException(status_code=500, detail="The command could not be started.") from exc
    if run["state"] == "failed_to_start":
        _not_started(req, run["reason"])
    return {"ok": True, "request_id": req.id, "run": run}


def _not_started(req, why: str) -> None:
    """A claimed request whose run never began must not stay 'running' for the model and the card."""
    host_requests.finish(req.id, {"error": f"The command did not start: {why}.", "stdout": "", "stderr": "",
                                  "exit_code": -1, "ran_on": "host", "cwd": req.cwd})


@router.post("/api/host-shell/{request_id}/cancel", dependencies=[Depends(verify_csrf)])
def cancel_host_command(request_id: str, body: HostShellDecision):
    """Cancel a pending request, or stop a running one by killing its whole process tree."""
    with _one_at_a_time(request_id):
        return _cancel_locked(request_id, body)


def _cancel_locked(request_id: str, body: HostShellDecision):
    host_requests.sync_expiry()
    supervisor = get_supervisor()
    try:
        run = supervisor.get(request_id, body.context_id)
        if run is None:
            raise HTTPException(status_code=404, detail="This command request was not found or has expired.")
        if run["state"] in ("preparing", "running"):
            run = supervisor.cancel(request_id, body.context_id)
        elif run["state"] == "awaiting_approval":
            host_requests.deny(request_id, body.context_id)
            run = supervisor.deny(request_id, body.context_id)
    except (host_requests.HostRequestError, RunError) as exc:
        raise _http(exc) from exc
    return {"ok": True, "request_id": request_id, "status": run["state"], "run": run}


@router.get("/api/host-shell/{request_id}")
def host_command_status(request_id: str, context_id: str = ""):
    """The run record for a card, plus the stored result once the command is over."""
    host_requests.sync_expiry()
    run = get_supervisor().get(request_id, context_id)
    if run is None:
        raise HTTPException(status_code=404, detail="This command request was not found or has expired.")
    status, req = host_requests.lookup_settled(request_id, context_id)
    result = req.result if req is not None and status == "done" else None
    return {"ok": True, "request_id": request_id, "run": run, "result": result}
