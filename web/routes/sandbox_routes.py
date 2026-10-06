"""Code-runner sandbox routes: approval decisions, status, opt-out.

Approve/deny and opt-out are guarded by verify_csrf (same guard as
/api/drafts/{id}/approve), so the in-process agent loop cannot forge them.
"""
from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

import sandbox
from sandbox import approvals
from sandbox.policy import load_policy
from security import verify_csrf

router = APIRouter()
_log = logging.getLogger(__name__)


class SandboxDecisionRequest(BaseModel):
    context_id: str = ""


class SandboxOptOutRequest(BaseModel):
    opted_out: bool


def _decide(request_id: str, body: SandboxDecisionRequest, approve: bool) -> dict:
    try:
        req = approvals.decide(request_id, body.context_id, approve)
    except approvals.ApprovalError as exc:
        raise HTTPException(status_code=exc.status_code, detail=str(exc)) from exc
    # Metadata only: never log the paths or hosts.
    _log.info("sandbox approval decision=%s", req.status)
    return {"ok": True, "request_id": req.id, "status": req.status}


@router.post("/api/sandbox/requests/{request_id}/approve", dependencies=[Depends(verify_csrf)])
def approve_sandbox_request(request_id: str, body: SandboxDecisionRequest):
    return _decide(request_id, body, True)


@router.post("/api/sandbox/requests/{request_id}/deny", dependencies=[Depends(verify_csrf)])
def deny_sandbox_request(request_id: str, body: SandboxDecisionRequest):
    return _decide(request_id, body, False)


@router.get("/api/sandbox/status")
def sandbox_status():  # sync: the first call probes the OS sandbox
    from config import load_config

    policy = load_policy()
    return {
        "level": sandbox.sandbox_level(),
        "reason": sandbox.sandbox_unavailable_reason(),
        # Effective value: a policy that requires the sandbox overrides a stored opt-out.
        "opted_out": load_config().get("code_runner_sandbox") == "off" and not policy.require_sandbox,
        "policy": policy.as_dict(),
    }


@router.post("/api/sandbox/opt-out", dependencies=[Depends(verify_csrf)])
def set_sandbox_opt_out(body: SandboxOptOutRequest):
    if load_policy().require_sandbox:
        raise HTTPException(status_code=409, detail="Your administrator requires the code sandbox; it cannot be turned off.")
    from config import update_config

    def _apply(cfg: dict) -> dict:
        if body.opted_out:
            cfg["code_runner_sandbox"] = "off"
        else:
            cfg.pop("code_runner_sandbox", None)
        return cfg

    update_config(_apply)
    return {"ok": True, "opted_out": body.opted_out}
