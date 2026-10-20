"""Import clips and audio into demo projects and edit the combined timeline."""

import asyncio
import uuid
from typing import Optional

from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel

import demo_clips as clips
import demo_compose as compose
import demo_media_probe as probe
import demo_projects as dp
from security import verify_csrf

router = APIRouter(prefix="/api/demo-media")

_STATUS = {
    "unsupported_type": 415, "too_large": 413, "project_locked": 409, "too_many": 409,
    "not_found": 404, "tools_missing": 503,
}
_TOO_LARGE = "That file is larger than the 2 GB limit."


def _fail(code: str, message: str) -> JSONResponse:
    return JSONResponse({"ok": False, "code": code, "message": message}, status_code=_STATUS.get(code, 422))


def _locked_message() -> str:
    return "This demo's narration is already approved. Start a new demo to change clips."


def _target_project(project_id: Optional[str]) -> str:
    if project_id:
        try:
            project = dp.get_project(project_id)
        except KeyError:
            raise clips.ClipError("not_found", "No such demo project.") from None
        if project["stage"] in clips.LOCKED_STAGES:
            raise clips.ClipError("project_locked", _locked_message())
        return project_id
    active = dp.get_active_id()
    if active:
        try:
            project = dp.get_project(active)
        except KeyError:
            project = None
        if project and project["stage"] not in clips.LOCKED_STAGES:
            reg = clips.load(active)
            if project["stage"] == "created" or reg["clips"] or reg["audio"]:
                return active
    return dp.create_project()["project_id"]


@router.post("/upload", dependencies=[Depends(verify_csrf)])
async def upload(request: Request, filename: str = Query(...), project_id: Optional[str] = Query(None)):
    part = None
    try:
        if probe.extension_kind(filename) is None:
            probe.probe_media(filename)
        if int(request.headers.get("content-length") or 0) > probe.MAX_FILE_BYTES:
            raise probe.MediaRejected("too_large", _TOO_LARGE)
        pid = await asyncio.to_thread(_target_project, project_id)
        part = clips.abs_path(pid, "source") / f".upload_{uuid.uuid4().hex}.part"
        part.parent.mkdir(parents=True, exist_ok=True)
        size = 0
        with open(part, "wb") as handle:
            async for chunk in request.stream():
                size += len(chunk)
                if size > probe.MAX_FILE_BYTES:
                    raise probe.MediaRejected("too_large", _TOO_LARGE)
                await asyncio.to_thread(handle.write, chunk)
        info = await asyncio.to_thread(probe.probe_media, part, filename)
        item = await asyncio.to_thread(clips.add_item, pid, part, filename, info)
    except (clips.ClipError, probe.MediaRejected) as exc:
        return _fail(exc.code, exc.message)
    finally:
        if part is not None:
            part.unlink(missing_ok=True)
    compose.schedule(pid)
    return {"ok": True, "project_id": pid, "item": item,
            "path": str(clips.abs_path(pid, item["file"])), "clips": clips.load(pid)}


@router.get("/{pid}")
def get_media(pid: str):
    try:
        project = dp.get_project(pid)
    except KeyError:
        return _fail("not_found", "No such demo project.")
    compose.ensure_current(pid)
    return {"ok": True, "project_id": pid, "name": project["name"], "stage": project["stage"],
            "clips": clips.load(pid)}


def _apply(pid: str, action):
    try:
        _target_project(pid)
        action()
    except clips.ClipError as exc:
        return _fail(exc.code, exc.message)
    compose.schedule(pid)
    return {"ok": True, "clips": clips.load(pid)}


class OrderBody(BaseModel):
    ids: list[str]


class TrimBody(BaseModel):
    trim_start: float = 0.0
    trim_end: Optional[float] = None


@router.put("/{pid}/order", dependencies=[Depends(verify_csrf)])
def put_order(pid: str, body: OrderBody):
    return _apply(pid, lambda: clips.reorder(pid, body.ids))


@router.patch("/{pid}/clips/{cid}", dependencies=[Depends(verify_csrf)])
def patch_clip(pid: str, cid: str, body: TrimBody):
    return _apply(pid, lambda: clips.set_trim(pid, cid, body.trim_start, body.trim_end))


@router.delete("/{pid}/items/{iid}", dependencies=[Depends(verify_csrf)])
def delete_item(pid: str, iid: str):
    return _apply(pid, lambda: clips.remove_item(pid, iid))
