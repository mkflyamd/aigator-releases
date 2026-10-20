"""Serve an image shown inline in chat so the UI can download or save it.

Only /api/files/ outputs and https images on INLINE_IMAGE_HOSTS are served; keep
that list in sync with INLINE_IMAGE_HOSTS in web/static/app.js (a test enforces it).
"""

import asyncio
import hashlib
import re
from pathlib import Path
from urllib.parse import unquote, urlsplit

import httpx
from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import Response
from pydantic import BaseModel
from security import verify_csrf

from routes import files
from routes.utils import _open_file_dialog

router = APIRouter()

INLINE_IMAGE_HOSTS = ("mcp-platform.amd.com",)
_MAX_BYTES = 25 * 1024 * 1024
_EXT_BY_TYPE = {
    "image/png": ".png",
    "image/jpeg": ".jpg",
    "image/webp": ".webp",
    "image/gif": ".gif",
}
_TYPE_BY_EXT = {
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".webp": "image/webp",
    ".gif": "image/gif",
}
_LOCAL_PATH = re.compile(r"^/api/files/([^/]+)/([^/]+)$")
_fetch_locks: dict[str, asyncio.Lock] = {}


async def _fetch_remote(url: str) -> tuple[bytes, str]:
    async with (
        httpx.AsyncClient(follow_redirects=False, timeout=20) as client,
        client.stream("GET", url) as resp,
    ):
        resp.raise_for_status()
        content_type = (
            resp.headers.get("content-type", "").split(";")[0].strip().lower()
        )
        data = bytearray()
        async for chunk in resp.aiter_bytes():
            data += chunk
            if len(data) > _MAX_BYTES:
                raise ValueError("image too large")
    return bytes(data), content_type


def _load_local(path: str) -> tuple[bytes, str, str]:
    match = _LOCAL_PATH.match(path)
    if not match:
        raise HTTPException(status_code=400, detail="Unsupported image URL")
    run_id, filename = unquote(match.group(1)), unquote(match.group(2))
    content_type = _TYPE_BY_EXT.get(Path(filename).suffix.lower())
    if not content_type:
        raise HTTPException(status_code=400, detail="Not an image")
    try:
        target = files._safe_output_path(run_id, filename)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid path")
    if not target.is_file():
        raise HTTPException(status_code=404, detail="Image not found")
    if target.stat().st_size > _MAX_BYTES:
        raise HTTPException(status_code=413, detail="Image too large")
    return target.read_bytes(), content_type, filename


async def _load_remote(url: str) -> tuple[bytes, str, str]:
    parts = urlsplit(url)
    if (
        parts.scheme != "https"
        or parts.hostname not in INLINE_IMAGE_HOSTS
        or parts.username
        or parts.password
        or parts.port not in (None, 443)
    ):
        raise HTTPException(status_code=400, detail="Unsupported image URL")
    name = unquote(parts.path.rsplit("/", 1)[-1])
    # Remote links are short-lived and may be single-use, and the browser's own
    # <img> request can use them up. Fetch once, keep the bytes under the outputs
    # dir (cleaned up after 24h) and serve display, download and save from there.
    key = hashlib.sha256(url.encode()).hexdigest()[:32]
    folder = files.OUTPUTS_DIR / f"inline-{key}"
    async with _fetch_locks.setdefault(key, asyncio.Lock()):
        cached = next(folder.glob("cached.*"), None) if folder.is_dir() else None
        if cached and cached.suffix in _TYPE_BY_EXT:
            return cached.read_bytes(), _TYPE_BY_EXT[cached.suffix], name
        try:
            data, content_type = await _fetch_remote(url)
        except (httpx.HTTPError, ValueError):
            raise HTTPException(status_code=502, detail="Image is no longer available")
        if content_type not in _EXT_BY_TYPE:
            raise HTTPException(status_code=502, detail="Not an image")
        folder.mkdir(parents=True, exist_ok=True)
        (folder / f"cached{_EXT_BY_TYPE[content_type]}").write_bytes(data)
    return data, content_type, name


async def _load_image(url: str) -> tuple[bytes, str, str]:
    """Return (bytes, content_type, safe_filename) or raise HTTPException."""
    if url.startswith("/"):
        data, content_type, name = _load_local(urlsplit(url).path)
    else:
        data, content_type, name = await _load_remote(url)
    stem = re.sub(r"[^A-Za-z0-9._ -]", "_", Path(name).stem)[:80] or "image"
    return data, content_type, stem + _EXT_BY_TYPE[content_type]


@router.get("/api/inline-image")
async def download_inline_image(url: str = ""):
    data, content_type, filename = await _load_image(url)
    return Response(
        content=data,
        media_type=content_type,
        headers={
            "Content-Disposition": f'attachment; filename="{filename}"',
            "X-Content-Type-Options": "nosniff",
        },
    )


class SaveInlineImageRequest(BaseModel):
    url: str


@router.post("/api/inline-image/save", dependencies=[Depends(verify_csrf)])
async def save_inline_image(req: SaveInlineImageRequest):
    """Fetch the image, ask the user where to put it, and write it there."""
    data, _, filename = await _load_image(req.url)
    ext = Path(filename).suffix
    chosen = await asyncio.get_running_loop().run_in_executor(
        None,
        _open_file_dialog,
        "Save image as",
        f"Image (*{ext})|*{ext}|All files (*.*)|*.*",
        True,
        filename,
    )
    if not chosen:
        return {"ok": False, "cancelled": True}
    dest = Path(chosen)
    if not dest.suffix:
        dest = dest.with_suffix(ext)
    try:
        dest.write_bytes(data)
    except OSError as exc:
        raise HTTPException(
            status_code=500, detail=f"Could not write file: {exc.strerror}"
        )
    return {"ok": True, "file_path": str(dest)}
