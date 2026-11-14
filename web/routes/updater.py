"""REST API for OTA update status and actions."""

import asyncio
from fastapi import APIRouter
import updater

router = APIRouter()


@router.get("/api/update/status")
def get_update_status():
    s = updater._state
    return {
        "state": s.state,
        "available": s.state in ("available", "downloading", "ready", "error"),
        "version": s.info.version if s.info else None,
        "notes": s.info.notes if s.info else None,
        "progress": s.progress,
        "error": s.error,
        "install_supported": bool(s.info and s.info.install_supported),
        "release_url": updater.RELEASE_PAGE_URL,
    }


@router.post("/api/update/download")
async def start_download():
    if updater._state.state not in ("available", "error"):
        return {"ok": False, "reason": "No update available"}
    if updater._state.info is None:
        return {"ok": False, "reason": "No update available"}
    if not updater._state.info.install_supported:
        return {"ok": False, "reason": "In-app install is not available for this release"}
    updater._state.state = "downloading"
    asyncio.create_task(updater.download_update())
    return {"ok": True}


@router.post("/api/update/install")
def install_update():
    if updater._state.state != "ready":
        return {"ok": False, "reason": "Update not ready"}
    updater.launch_installer()
    return {"ok": True}
