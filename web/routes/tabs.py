"""Tab registry endpoints — client syncs its tab list here."""
from fastapi import APIRouter
from pydantic import BaseModel

from skills.context import tabs as _tabs

router = APIRouter()


class TabEntry(BaseModel):
    id: str
    name: str | None = None
    title: str | None = None


class SyncRequest(BaseModel):
    tabs: list[TabEntry]


@router.post("/api/tabs/sync")
async def sync_tabs(req: SyncRequest):
    """Replace the server-side registry with the client's current tabs."""
    return _tabs.sync([t.model_dump() for t in req.tabs])


@router.get("/api/tabs")
async def list_tabs():
    return {"tabs": _tabs.list_tabs()}
