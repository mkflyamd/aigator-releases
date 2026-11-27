"""The Remote control switch: one 12 hour window for Teams and Slack."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException

from remote import status
from remote.state import shared
from security import verify_csrf

router = APIRouter()


@router.get("/api/remote/status")
def remote_status():
    return status.compute(shared())


@router.post("/api/remote/arm", dependencies=[Depends(verify_csrf)])
def remote_arm():
    refused = status.arm(shared())
    if refused:
        raise HTTPException(status_code=409, detail=status.reason(refused))
    return status.compute(shared())


@router.post("/api/remote/disarm", dependencies=[Depends(verify_csrf)])
def remote_disarm():
    status.disarm(shared())
    return status.compute(shared())
