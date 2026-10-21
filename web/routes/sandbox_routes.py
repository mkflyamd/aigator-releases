"""Code-runner sandbox routes: approval decisions, status, opt-out.

Approve/deny and opt-out are guarded by verify_csrf (same guard as
/api/drafts/{id}/approve), so the in-process agent loop cannot forge them.
"""
from __future__ import annotations

import logging
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

import sandbox
from sandbox import approvals, saved_permissions, task_grants
from sandbox.policy import load_policy
from security import verify_csrf

router = APIRouter()
_log = logging.getLogger(__name__)


class SandboxDecisionRequest(BaseModel):
    context_id: str = ""
    scope: Literal["once", "task", "always"] = "once"


class SandboxOptOutRequest(BaseModel):
    opted_out: bool


def _decide(request_id: str, body: SandboxDecisionRequest, approve: bool) -> dict:
    allow_saved = load_policy().saved_permissions != "deny"
    try:
        req = approvals.decide(request_id, body.context_id, approve, scope=body.scope, allow_saved=allow_saved)
    except approvals.ApprovalError as exc:
        raise HTTPException(status_code=exc.status_code, detail=str(exc)) from exc
    saved = False
    if approve:
        if req.scope == "always":
            try:
                saved_permissions.add(req.read_paths, req.write_paths, bool(req.network_hosts), req.programs or ())
                saved = True
            except Exception as exc:
                _log.warning("saving a permission failed (%s); using a task approval", type(exc).__name__)
                req.scope = "task"
        if req.scope == "task":
            task_grants.add(req.context_id, req.read_paths, req.write_paths, req.network_hosts)
    # Metadata only: never log the paths, hosts or command.
    _log.info("sandbox approval decision=%s scope=%s saved=%s", req.status, req.scope, saved)
    return {"ok": True, "request_id": req.id, "status": req.status, "scope": req.scope, "saved": saved}


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


@router.get("/api/sandbox/saved-permissions", dependencies=[Depends(verify_csrf)])
def list_saved_permissions():
    return {"entries": [{"id": e["id"], "description": saved_permissions.describe(e), "created": e["created"]}
                        for e in saved_permissions.list_entries()]}


@router.delete("/api/sandbox/saved-permissions/{entry_id}", dependencies=[Depends(verify_csrf)])
def remove_saved_permission(entry_id: str):
    if not saved_permissions.remove(entry_id):
        raise HTTPException(status_code=404, detail="That saved permission was not found.")
    return {"ok": True}


@router.delete("/api/sandbox/saved-permissions", dependencies=[Depends(verify_csrf)])
def remove_all_saved_permissions():
    saved_permissions.remove_all()
    return {"ok": True}
