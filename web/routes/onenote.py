"""OneNote + universal context pin route group."""

import asyncio
import json
import re
import time
from pathlib import Path

from fastapi import APIRouter, Body, HTTPException
from pydantic import BaseModel

import shared

ROOT = Path(__file__).parent.parent.parent

router = APIRouter()

# ── In-memory cache for OneNote list endpoints ───────────────────────────────
# Graph OneNote endpoints are throttled (~4 req/30s). Cache aggressively.
_ONENOTE_CACHE: dict = {}
_ONENOTE_CACHE_TTL = 300   # 5 min — OneNote quota recovers slowly; cache must outlive it
_ONENOTE_429_TTL   = 60    # 60s back-off after 429 — conservative, Graph window is 30-60s
_ONENOTE_INFLIGHT: dict = {}  # key -> asyncio.Lock, prevents stampede on cache miss
_ONENOTE_INFLIGHT_MAX = 200

def _cache_get(key: str):
    entry = _ONENOTE_CACHE.get(key)
    if not entry:
        return None
    ttl = _ONENOTE_429_TTL if entry.get('is_429') else _ONENOTE_CACHE_TTL
    if time.time() - entry['ts'] < ttl:
        return entry  # return full entry so caller can inspect is_429
    return None

def _cache_set(key: str, data):
    _ONENOTE_CACHE[key] = {'data': data, 'ts': time.time(), 'is_429': False}

def _cache_set_429(key: str):
    _ONENOTE_CACHE[key] = {'data': None, 'ts': time.time(), 'is_429': True}

async def _cached_onenote_fetch(key: str, fn, *args):
    """Fetch with cache + per-key lock. Caches 429s for 35s to prevent retry storms."""
    entry = _cache_get(key)
    if entry is not None:
        if entry.get('is_429'):
            raise HTTPException(status_code=429, detail='OneNote rate limit hit — please wait a moment and retry.')
        return entry['data']
    if key not in _ONENOTE_INFLIGHT:
        if len(_ONENOTE_INFLIGHT) >= _ONENOTE_INFLIGHT_MAX:
            for old in list(_ONENOTE_INFLIGHT.keys())[:10]:
                _ONENOTE_INFLIGHT.pop(old, None)
        _ONENOTE_INFLIGHT[key] = asyncio.Lock()
    async with _ONENOTE_INFLIGHT[key]:
        entry = _cache_get(key)
        if entry is not None:
            if entry.get('is_429'):
                raise HTTPException(status_code=429, detail='OneNote rate limit hit — please wait a moment and retry.')
            return entry['data']
        try:
            result = await asyncio.to_thread(fn, *args)
            _cache_set(key, result)
            return result
        except Exception as e:
            if '429' in str(e):
                _cache_set_429(key)
                raise HTTPException(status_code=429, detail='OneNote rate limit hit — please wait a moment and retry.')
            raise


# ── Pydantic models ──────────────────────────────────────────────────────────


class OneNotePinRequest(BaseModel):
    page_id: str
    page_title: str
    notebook_name: str = ""
    section_name: str = ""
    context_id: str = "default"


class ContextPinRequest(BaseModel):
    source: str
    id: str
    label: str
    meta: dict = {}
    context_id: str = "default"


class OneNoteUpdatePageRequest(BaseModel):
    body: str
    html: bool = False


class OneNoteCreatePageRequest(BaseModel):
    title: str
    body: str
    html: bool = False


# ── OneNote pin routes ───────────────────────────────────────────────────────


@router.post("/api/onenote/pin")
async def tp_onenote_pin(req: OneNotePinRequest):
    """Pin a OneNote page -- delegates to universal context pin service."""
    from skills.context.state import set_pin
    result = set_pin("onenote", req.page_id, req.page_title,
                     {"notebook": req.notebook_name, "section": req.section_name},
                     req.context_id)
    # Also update legacy state for backward compat with onenote tools
    from skills.onenote.state import pinned_onenote_pages
    pinned_onenote_pages[req.page_title.lower()] = {
        "page_id": req.page_id, "title": req.page_title,
        "notebook": req.notebook_name, "section": req.section_name,
    }
    return result


@router.get("/api/onenote/pins")
async def tp_onenote_list_pins(context_id: str = "default"):
    """List pinned OneNote pages via universal pin service."""
    from skills.context.state import get_pins
    return [p for p in get_pins(context_id) if p.get("source") == "onenote"]


@router.delete("/api/onenote/pin/{page_id:path}")
async def tp_onenote_unpin(page_id: str, context_id: str = "default"):
    """Unpin a OneNote page via universal pin service."""
    from skills.context.state import remove_pin
    result = remove_pin("onenote", page_id, context_id)
    # Also clean legacy state
    from skills.onenote.state import pinned_onenote_pages
    to_remove = [k for k, v in pinned_onenote_pages.items() if v["page_id"] == page_id]
    for k in to_remove:
        del pinned_onenote_pages[k]
    return {"ok": True, "unpinned": page_id}


# ── Universal Context Pin Service ────────────────────────────────────────────


@router.post("/api/context/pin")
async def context_pin(req: ContextPinRequest):
    from skills.context.state import set_pin
    result = set_pin(req.source, req.id, req.label, req.meta, req.context_id)
    # Sync to legacy skill-specific state so tools can reference pinned items
    if req.source == "onenote":
        from skills.onenote.state import pinned_onenote_pages
        pinned_onenote_pages[req.label.lower()] = {
            "page_id": req.id, "title": req.label,
            "notebook": req.meta.get("notebook", ""),
            "section": req.meta.get("section", ""),
        }
    return result


@router.get("/api/context/pins")
async def context_list_pins(context_id: str = "default"):
    from skills.context.state import get_pins
    return get_pins(context_id)


@router.delete("/api/context/pin/{source}/{item_id:path}")
async def context_unpin(source: str, item_id: str, context_id: str = "default"):
    from skills.context.state import remove_pin
    result = remove_pin(source, item_id, context_id)
    # Sync legacy state
    if source == "onenote":
        from skills.onenote.state import pinned_onenote_pages
        to_remove = [k for k, v in pinned_onenote_pages.items() if v.get("page_id") == item_id]
        for k in to_remove:
            del pinned_onenote_pages[k]
    return result


@router.post("/api/context/pins/clone")
async def context_clone_pins(req: dict = Body(...)):
    """Clone all pins from one context_id to another."""
    from skills.context.state import get_pins, set_pin
    source_ctx = req.get("from_context_id", "default")
    target_ctx = req.get("to_context_id")
    if not target_ctx:
        return {"ok": False, "error": "to_context_id is required"}
    pins = get_pins(source_ctx)
    for p in pins:
        set_pin(p["source"], p["id"], p["label"], p.get("meta", {}), target_ctx)
    return {"ok": True, "cloned": len(pins)}


@router.delete("/api/context/pins")
async def context_clear_pins(context_id: str = "default"):
    from skills.context.state import clear_pins
    return clear_pins(context_id)


# ── Third Pane: OneNote endpoints ────────────────────────────────────────────

@router.get("/api/onenote/notebooks")
async def tp_onenote_notebooks():
    """List all OneNote notebooks (cached 2 min, stampede-safe, 429 back-off cached)."""
    from skills.onenote.tools import _tool_list_onenote_notebooks
    return await _cached_onenote_fetch('notebooks', _tool_list_onenote_notebooks)


@router.get("/api/onenote/notebooks/{notebook_id}/sections")
async def tp_onenote_sections(notebook_id: str):
    """List sections in a notebook (cached 2 min, stampede-safe, 429 back-off cached)."""
    from skills.onenote.tools import _tool_list_onenote_sections
    return await _cached_onenote_fetch(f'sections:{notebook_id}', _tool_list_onenote_sections, notebook_id)


@router.get("/api/onenote/sections/{section_id}/pages")
async def tp_onenote_pages(section_id: str):
    """List pages in a section (cached 2 min, stampede-safe, 429 back-off cached)."""
    from skills.onenote.tools import _tool_list_onenote_pages
    return await _cached_onenote_fetch(f'pages:{section_id}', _tool_list_onenote_pages, section_id)


@router.get("/api/onenote/pages/{page_id}")
async def tp_onenote_page_content(page_id: str):
    """Fetch page content as HTML. Graph images are rewritten to lazy-proxy URLs."""
    def _fetch_page():
        import urllib.request as _ur
        from skills._m365.helpers import get_skill_client
        _onenote_skills_dir = Path(__file__).parent.parent / "skills" / "m365-onenote" / "scripts"
        gc = get_skill_client(_onenote_skills_dir)
        token = gc.get_token()

        url = f"https://graph.microsoft.com/v1.0/me/onenote/pages/{page_id}/content"
        req = _ur.Request(url, headers={"Authorization": f"Bearer {token}", "Accept": "text/html"}, method="GET")
        with _ur.urlopen(req, timeout=30) as resp:
            body_html = resp.read().decode("utf-8", errors="replace")

        # Strip absolute positioning (breaks layout in our pane)
        body_html = re.sub(r'position:\s*absolute\s*;?', '', body_html)
        body_html = re.sub(r'(left|top):\s*\d+px\s*;?', '', body_html)

        # Rewrite Graph image URLs to our proxy endpoint — avoids per-image
        # serial Graph calls which made page load 1-8s per image.
        import urllib.parse as _up
        def _rewrite_img(match):
            img_url = match.group(1)
            if 'graph.microsoft.com' not in img_url:
                return match.group(0)
            return f'src="/api/onenote/proxy-image?url={_up.quote(img_url, safe="")}"'

        body_html = re.sub(r'src="(https://graph\.microsoft\.com/[^"]+)"', _rewrite_img, body_html)

        meta = gc.get(f"/me/onenote/pages/{page_id}",
                      params={"$select": "id,title,lastModifiedDateTime,links"})
        return {
            "id": page_id,
            "title": meta.get("title", "(untitled)"),
            "modified": meta.get("lastModifiedDateTime", ""),
            "body_html": body_html,
            "url": (meta.get("links") or {}).get("oneNoteWebUrl", {}).get("href", ""),
        }

    try:
        return await asyncio.to_thread(_fetch_page)
    except Exception as e:
        msg = str(e)
        status = 429 if '429' in msg else 500
        raise HTTPException(status_code=status, detail=msg)


# ── OneNote image proxy (lazy-loads Graph-hosted images with auth) ──────────
import urllib.parse as _up
from collections import OrderedDict as _OD
from fastapi.responses import Response as _ImgResp

_onenote_img_cache: "_OD[str, tuple[str, bytes]]" = _OD()
_ONENOTE_IMG_CACHE_MAX = 100

@router.get("/api/onenote/proxy-image")
async def tp_onenote_proxy_image(url: str):
    """Proxy a Graph-hosted OneNote image with auth. SSRF-safe, cached."""
    parsed = _up.urlparse(url)
    host = parsed.netloc.lower().split(":")[0]
    if not (host == "graph.microsoft.com" or host.endswith(".graph.microsoft.com")):
        raise HTTPException(status_code=400, detail="URL not from graph.microsoft.com")

    if url in _onenote_img_cache:
        _onenote_img_cache.move_to_end(url)
        ct, data = _onenote_img_cache[url]
        return _ImgResp(content=data, media_type=ct, headers={"Cache-Control": "private, max-age=3600"})

    def _fetch_img():
        import urllib.request as _ur
        from skills._m365.helpers import get_skill_client
        _onenote_skills_dir = Path(__file__).parent.parent / "skills" / "m365-onenote" / "scripts"
        gc = get_skill_client(_onenote_skills_dir)
        token = gc.get_token()
        req = _ur.Request(url, headers={"Authorization": f"Bearer {token}"}, method="GET")
        with _ur.urlopen(req, timeout=15) as resp:
            ct = resp.headers.get('Content-Type', 'image/png').split(';')[0]
            return ct, resp.read()

    try:
        ct, data = await asyncio.to_thread(_fetch_img)
        if len(_onenote_img_cache) >= _ONENOTE_IMG_CACHE_MAX:
            _onenote_img_cache.popitem(last=False)
        _onenote_img_cache[url] = (ct, data)
        return _ImgResp(content=data, media_type=ct, headers={"Cache-Control": "private, max-age=3600"})
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Image fetch failed: {e}")


@router.patch("/api/onenote/pages/{page_id}")
async def tp_onenote_update_page(page_id: str, req: OneNoteUpdatePageRequest):
    """Append content to a OneNote page via the Graph API PATCH endpoint."""
    import urllib.request as _ur, urllib.error as _ue

    def _do_patch():
        from skills._m365.helpers import get_skill_client
        _onenote_skills_dir = Path(__file__).parent.parent / "skills" / "m365-onenote" / "scripts"
        gc = get_skill_client(_onenote_skills_dir)
        token = gc.get_token()

        body_content = req.body
        if not req.html:
            body_content = body_content.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace("\n", "<br/>")

        patch_ops = [{"target": "body", "action": "append", "content": f"<div>{body_content}</div>"}]
        url = f"https://graph.microsoft.com/v1.0/me/onenote/pages/{page_id}/content"
        data = json.dumps(patch_ops).encode()
        api_req = _ur.Request(url, data=data, headers={
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
        }, method="PATCH")
        with _ur.urlopen(api_req, timeout=30) as resp:
            pass
        return {"ok": True}

    try:
        return await asyncio.to_thread(_do_patch)
    except _ue.HTTPError as e:
        detail = e.read().decode()[:300]
        raise HTTPException(status_code=e.code, detail=detail)
    except Exception as e:
        msg = str(e)
        raise HTTPException(status_code=429 if '429' in msg else 500, detail=msg)


@router.post("/api/onenote/sections/{section_id}/pages")
async def tp_onenote_create_page(section_id: str, req: OneNoteCreatePageRequest):
    """Create a new page in a section."""
    try:
        from skills.onenote.tools import _tool_create_onenote_page
        result = await asyncio.to_thread(_tool_create_onenote_page, section_id, req.title, req.body, req.html)
        return result
    except Exception as e:
        msg = str(e)
        raise HTTPException(status_code=429 if '429' in msg else 500, detail=msg)
