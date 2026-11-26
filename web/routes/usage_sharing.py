"""Usage sharing: read-only delivery status."""

from fastapi import APIRouter

import shared
import usage_report

router = APIRouter()


@router.get("/api/usage-sharing")
async def get_usage_sharing():
    return usage_report.delivery_status(shared.cfg)
