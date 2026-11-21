from __future__ import annotations

import base64
import binascii
import uuid

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import Response
from pydantic import BaseModel

from security import verify_csrf

router = APIRouter()

_PNG_MAGIC = b"\x89PNG\r\n\x1a\n"
_MAX_IMAGE = 5 * 1024 * 1024
_MAX_TEXT = 20_000
_FAILURE_STATUSES = {"pane_not_visible", "page_mismatch", "pane_unavailable", "timeout"}


def _custom_apps() -> list[dict]:
    from config import load_config

    return load_config().get("custom_apps", [])


def _decode_png(image_b64: str) -> bytes:
    try:
        raw = base64.b64decode(image_b64, validate=True)
    except (binascii.Error, ValueError):
        raise HTTPException(400, "image_b64 is not valid base64")
    if len(raw) > _MAX_IMAGE:
        raise HTTPException(413, "image too large")
    if not raw.startswith(_PNG_MAGIC):
        raise HTTPException(400, "image must be a PNG")
    return raw


def _check_text(text: str | None) -> None:
    if text is not None and len(text) > _MAX_TEXT:
        raise HTTPException(413, "text too large")


class WebPinCreate(BaseModel):
    context_id: str
    app_id: str
    image_b64: str
    text: str = ""
    locator: dict | None = None
    url: str = ""
    title: str = ""
    aria_label: str = ""


class WebPinSnapshot(BaseModel):
    request_id: str | None = None
    status: str = "ok"
    image_b64: str | None = None
    text: str | None = None
    match: str | None = None


@router.post("/api/web-pins", dependencies=[Depends(verify_csrf)])
async def create_web_pin(req: WebPinCreate):
    from skills.context.state import set_pin
    from skills.webpin import store

    app_cfg = next((a for a in _custom_apps() if a.get("id") == req.app_id), None)
    if not app_cfg:
        raise HTTPException(400, "unknown custom app")
    image = _decode_png(req.image_b64)
    _check_text(req.text)
    pin_id = str(uuid.uuid4())
    label = store.sanitize_label(req.aria_label) or store.sanitize_label(req.title) or store.sanitize_label(app_cfg.get("name", "")) or "Web view"
    kind = "element" if req.locator else "view"
    snap = store.write_snapshot(
        pin_id,
        image=image,
        text=req.text,
        meta={"app_id": req.app_id, "url": req.url, "title": req.title, "aria_label": req.aria_label, "locator": req.locator, "kind": kind},
    )
    result = set_pin(
        "webpin", pin_id, label,
        {"app_id": req.app_id, "app_name": app_cfg.get("name", ""), "url": req.url, "title": req.title, "kind": kind, "captured_at": snap["captured_at"]},
        req.context_id,
    )
    return {"id": pin_id, "label": label, "captured_at": snap["captured_at"], "text_hash": snap["text_hash"], "total": result["total"]}


def _snapshot_or_404(pin_id: str) -> dict:
    from skills.webpin import store

    try:
        snap = store.read_snapshot(pin_id)
    except ValueError:
        snap = None
    if not snap:
        raise HTTPException(404, "web pin not found")
    return snap


@router.get("/api/web-pins/{pin_id}")
async def get_web_pin(pin_id: str):
    from skills.webpin import store

    snap = _snapshot_or_404(pin_id)
    return {"id": pin_id, **snap, "has_image": store.read_image(pin_id) is not None}


@router.get("/api/web-pins/{pin_id}/image")
async def get_web_pin_image(pin_id: str):
    from skills.webpin import store

    _snapshot_or_404(pin_id)
    img = store.read_image(pin_id)
    if img is None:
        raise HTTPException(404, "no image")
    return Response(content=img, media_type="image/png", headers={"Cache-Control": "no-store"})


@router.post("/api/web-pins/{pin_id}/snapshot", dependencies=[Depends(verify_csrf)])
async def post_web_pin_snapshot(pin_id: str, req: WebPinSnapshot):
    from skills.webpin import pending, store

    _snapshot_or_404(pin_id)
    if req.status != "ok":
        if req.status not in _FAILURE_STATUSES:
            raise HTTPException(400, "unknown status")
        if req.request_id and pending.resolve(req.request_id, pin_id, {"status": req.status}) == "conflict":
            raise HTTPException(409, "request already answered or unknown")
        return {"ok": False, "status": req.status}
    image = _decode_png(req.image_b64) if req.image_b64 else None
    _check_text(req.text)
    if req.request_id and not pending.claim(req.request_id, pin_id):
        raise HTTPException(409, "request already answered or unknown")
    meta = {"match": req.match} if req.match else {}
    snap = store.write_snapshot(pin_id, image=image, text=req.text, meta=meta)
    result = {"status": "ok", "changed": snap["changed"], "captured_at": snap["captured_at"], "match": req.match}
    if req.request_id:
        pending.finish(req.request_id, result)
    return {"ok": True, **result}
