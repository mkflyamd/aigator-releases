"""Run records for a tab: what a card or panel needs to find the runs it started, after a reload or a tab switch."""
from __future__ import annotations

from fastapi import APIRouter, Query

from runs.supervisor import get_supervisor
from sandbox import host_requests

router = APIRouter()


@router.get("/api/runs")
def list_runs(context_id: str = Query(..., min_length=1)):
    """The tab's run records, newest first."""
    host_requests.sync_expiry()
    return {"ok": True, "context_id": context_id, "runs": get_supervisor().list(context_id)}
