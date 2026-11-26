"""Usage-sharing consent: read delivery status, record the user's choice."""

import asyncio

from fastapi import APIRouter, Depends
from pydantic import BaseModel

import shared
import usage_report
from security import verify_csrf

router = APIRouter()


class UsageSharingChoice(BaseModel):
    enabled: bool


@router.get("/api/usage-sharing")
async def get_usage_sharing():
    return usage_report.delivery_status(shared.cfg)


@router.post("/api/usage-sharing", dependencies=[Depends(verify_csrf)])
async def set_usage_sharing(body: UsageSharingChoice):
    await asyncio.to_thread(usage_report.set_consent, "on" if body.enabled else "off")
    if body.enabled:
        usage_report.request_report()
    return usage_report.delivery_status(shared.cfg)
