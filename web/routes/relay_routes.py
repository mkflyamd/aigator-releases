"""Gator Relay settings and links: the user's side of agent-to-agent messaging.

Every change here is a user action guarded by verify_csrf, so an agent cannot grant
itself or a peer the right to message.
"""
from __future__ import annotations

import asyncio

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

import agent_wake
from relay import settings
from relay.core import MAX_LINK_SECONDS, recent_audit
from relay.model import Endpoint, pty_endpoint
from relay.service import get_relay
from security import verify_csrf

router = APIRouter()


class RelaySettingsRequest(BaseModel):
    enabled: bool


class RelayLinkRequest(BaseModel):
    a: str
    b: str
    hours: float = Field(default=8.0, gt=0, le=MAX_LINK_SECONDS / 3600)


class RelayOptOutRequest(BaseModel):
    endpoint_id: str
    opted_out: bool


def _endpoint(entry: dict) -> Endpoint:
    return pty_endpoint(entry["pty_id"], entry["title"] or entry["session_id"][:8], entry["project_id"])


@router.get("/api/relay", dependencies=[Depends(verify_csrf)])
async def relay_state():
    entries = await asyncio.to_thread(agent_wake.list_entries)
    agents = []
    for entry in entries:
        endpoint = _endpoint(entry)
        agents.append({**endpoint.as_dict(), "state": entry["state"], "opted_out": settings.opted_out(endpoint.id)})
    return {
        "admin_allows": settings.admin_allows_messaging(),
        "enabled": settings.user_allows_messaging(),
        "agents": agents,
        "links": get_relay().links(),
    }


@router.post("/api/relay/settings", dependencies=[Depends(verify_csrf)])
def set_relay_settings(body: RelaySettingsRequest):
    settings.set_user_messaging(body.enabled)
    return {"enabled": settings.user_allows_messaging()}


@router.post("/api/relay/links", dependencies=[Depends(verify_csrf)])
async def create_relay_link(body: RelayLinkRequest):
    if not settings.messaging_allowed():
        raise HTTPException(status_code=403, detail="Agent messaging is switched off.")
    ends = []
    for ref in (body.a, body.b):
        entry = await asyncio.to_thread(agent_wake.find_by_pty, ref.partition(":")[2]) if ref.startswith("pty:") else None
        if entry is None:
            raise HTTPException(status_code=404, detail="That agent is not available.")
        ends.append(_endpoint(entry))
    if ends[0].id == ends[1].id:
        raise HTTPException(status_code=400, detail="A link needs two different agents.")
    link = get_relay().create_link(ends[0], ends[1], body.hours * 3600)
    return next(item for item in get_relay().links() if item["id"] == link.id)


@router.delete("/api/relay/links/{link_id}", dependencies=[Depends(verify_csrf)])
def stop_relay_link(link_id: str):
    if not get_relay().stop_link(link_id):
        raise HTTPException(status_code=404, detail="No such link.")
    return {"stopped": link_id}


@router.post("/api/relay/links/{link_id}/resume", dependencies=[Depends(verify_csrf)])
def resume_relay_link(link_id: str):
    if not settings.messaging_allowed():
        raise HTTPException(status_code=403, detail="Agent messaging is switched off.")
    if not get_relay().resume_link(link_id):
        raise HTTPException(status_code=404, detail="No such link.")
    return {"resumed": link_id}


@router.post("/api/relay/stop-all", dependencies=[Depends(verify_csrf)])
def stop_all_relay():
    get_relay().stop_all()
    return {"stopped": True}


@router.post("/api/relay/opt-out", dependencies=[Depends(verify_csrf)])
def set_relay_opt_out(body: RelayOptOutRequest):
    if not body.endpoint_id.startswith("pty:"):
        raise HTTPException(status_code=400, detail="Unknown agent.")
    settings.set_opted_out(body.endpoint_id, body.opted_out)
    return {"endpoint_id": body.endpoint_id, "opted_out": settings.opted_out(body.endpoint_id)}


@router.get("/api/relay/audit", dependencies=[Depends(verify_csrf)])
def relay_audit(limit: int = 50):
    return {"events": recent_audit(max(1, min(limit, 200)))}
