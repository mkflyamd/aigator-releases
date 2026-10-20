"""Demo project routes — see docs/superpowers/specs/2026-10-19-demo-project-state-design.md."""

from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel

import demo_project_delivery as delivery
import demo_projects as dp
import narration_approval
from security import verify_csrf

router = APIRouter()

_MEDIA = {".mp4": "video/mp4", ".mp3": "audio/mpeg", ".m4a": "audio/mp4"}


class CreateProjectRequest(BaseModel):
    name: str | None = None
    root: str | None = None


class SettingsRequest(BaseModel):
    root: str | None = None


class NarrationRequest(BaseModel):
    segments: list
    flags: dict = {}


def _settings() -> dict:
    root = dp.get_default_root()
    return {"default_root": str(root), "is_default": root == dp.DEFAULT_ROOT}


def _bad(exc: Exception) -> HTTPException:
    return HTTPException(status_code=400, detail=str(exc))


def _get(project_id: str) -> dict:
    try:
        return dp.get_project(project_id)
    except KeyError:
        raise HTTPException(status_code=404, detail="Project not found") from None


@router.get("/api/demo-projects/settings")
async def get_settings():
    return _settings()


@router.put("/api/demo-projects/settings", dependencies=[Depends(verify_csrf)])
async def put_settings(req: SettingsRequest):
    try:
        dp.set_default_root(req.root)
    except ValueError as exc:
        raise _bad(exc)
    return _settings()


@router.get("/api/demo-projects")
async def list_projects():
    return {"projects": dp.list_projects(), "active_project_id": dp.get_active_id()}


@router.post("/api/demo-projects", dependencies=[Depends(verify_csrf)])
async def create_project(req: CreateProjectRequest):
    try:
        return dp.create_project(name=req.name, root=Path(req.root) if req.root else None)
    except ValueError as exc:
        raise _bad(exc)


@router.get("/api/demo-projects/active")
async def get_active():
    pid = dp.get_active_id()
    if not pid:
        raise HTTPException(status_code=404, detail="No active project")
    return _get(pid)


@router.get("/api/demo-projects/{project_id}")
async def get_project(project_id: str):
    return _get(project_id)


@router.post("/api/demo-projects/{project_id}/activate", dependencies=[Depends(verify_csrf)])
async def activate(project_id: str):
    try:
        dp.set_active(project_id)
    except KeyError:
        raise HTTPException(status_code=404, detail="Project not found") from None
    return dp.get_project(project_id)


@router.post("/api/demo-projects/{project_id}/narration", dependencies=[Depends(verify_csrf)])
async def narration(project_id: str, req: NarrationRequest):
    _get(project_id)
    try:
        return narration_approval.approve(project_id, req.segments, req.flags)
    except narration_approval.ApprovalError as exc:
        raise _bad(exc)


@router.get("/api/demo-projects/{project_id}/file")
async def serve_file(project_id: str, rel: str):
    _get(project_id)
    try:
        p = dp.resolve_file(project_id, rel)
    except ValueError:
        raise HTTPException(status_code=403, detail="path outside project") from None
    if not p.is_file():
        raise HTTPException(status_code=404, detail="file not found")
    return FileResponse(str(p), media_type=_MEDIA.get(p.suffix.lower(), "application/octet-stream"))


@router.get("/api/demo-projects/{project_id}/summary")
async def project_summary_route(project_id: str):
    _get(project_id)
    return delivery.project_summary(project_id)


@router.get("/api/demo-projects/{project_id}/progress")
async def project_progress_route(project_id: str):
    _get(project_id)
    return delivery.read_progress(project_id)
