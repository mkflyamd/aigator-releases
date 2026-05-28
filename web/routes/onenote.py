"""OneNote + universal context pin route group."""

import json
import re
from pathlib import Path

from fastapi import APIRouter, Body, HTTPException
from pydantic import BaseModel

import shared

ROOT = Path(__file__).parent.parent.parent

router = APIRouter()


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
    """List all OneNote notebooks."""
    try:
        from skills.onenote.tools import _tool_list_onenote_notebooks
        result = _tool_list_onenote_notebooks()
        return result
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/api/onenote/notebooks/{notebook_id}/sections")
async def tp_onenote_sections(notebook_id: str):
    """List sections in a notebook."""
    try:
        from skills.onenote.tools import _tool_list_onenote_sections
        result = _tool_list_onenote_sections(notebook_id)
        return result
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/api/onenote/sections/{section_id}/pages")
async def tp_onenote_pages(section_id: str):
    """List pages in a section."""
    try:
        from skills.onenote.tools import _tool_list_onenote_pages
        result = _tool_list_onenote_pages(section_id)
        return result
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/api/onenote/pages/{page_id}")
async def tp_onenote_page_content(page_id: str):
    """Fetch page content as HTML with images proxied to base64."""
    import urllib.request as _ur, urllib.error as _ue, base64 as _b64
    try:
        from skills._m365.helpers import get_skill_client
        _onenote_skills_dir = Path(__file__).parent.parent / "skills" / "m365-onenote" / "scripts"
        gc = get_skill_client(_onenote_skills_dir)
        token = gc.get_token()
        url = f"https://graph.microsoft.com/v1.0/me/onenote/pages/{page_id}/content"
        req = _ur.Request(url, headers={
            "Authorization": f"Bearer {token}",
            "Accept": "text/html",
        }, method="GET")
        with _ur.urlopen(req, timeout=30) as resp:
            body_html = resp.read().decode("utf-8", errors="replace")

        # Strip absolute positioning (OneNote uses it but it breaks in our pane)
        body_html = re.sub(r'position:\s*absolute\s*;?', '', body_html)
        body_html = re.sub(r'(left|top):\s*\d+px\s*;?', '', body_html)

        # Proxy Graph API image URLs to inline base64 (they require auth)
        def _proxy_img(match):
            img_url = match.group(1)
            if 'graph.microsoft.com' not in img_url:
                return match.group(0)
            try:
                img_req = _ur.Request(img_url, headers={"Authorization": f"Bearer {token}"}, method="GET")
                with _ur.urlopen(img_req, timeout=15) as img_resp:
                    ct = img_resp.headers.get('Content-Type', 'image/png')
                    data = _b64.b64encode(img_resp.read()).decode()
                    return f'src="data:{ct};base64,{data}"'
            except Exception:
                return match.group(0)

        body_html = re.sub(r'src="(https://graph\.microsoft\.com/[^"]+)"', _proxy_img, body_html)

        # Get page metadata (title, modified)
        meta = gc.get(f"/me/onenote/pages/{page_id}",
                      params={"$select": "id,title,lastModifiedDateTime,links"})
        return {
            "id": page_id,
            "title": meta.get("title", "(untitled)"),
            "modified": meta.get("lastModifiedDateTime", ""),
            "body_html": body_html,
            "url": (meta.get("links") or {}).get("oneNoteWebUrl", {}).get("href", ""),
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.patch("/api/onenote/pages/{page_id}")
async def tp_onenote_update_page(page_id: str, req: OneNoteUpdatePageRequest):
    """Append content to a OneNote page via the Graph API PATCH endpoint."""
    import urllib.request as _ur, urllib.error as _ue
    try:
        from skills._m365.helpers import get_skill_client
        _onenote_skills_dir = Path(__file__).parent.parent / "skills" / "m365-onenote" / "scripts"
        gc = get_skill_client(_onenote_skills_dir)
        token = gc.get_token()

        body_content = req.body
        if not req.html:
            body_content = body_content.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace("\n", "<br/>")

        # OneNote PATCH uses JSON array of operations
        patch_ops = [
            {
                "target": "body",
                "action": "append",
                "content": f"<div>{body_content}</div>"
            }
        ]

        url = f"https://graph.microsoft.com/v1.0/me/onenote/pages/{page_id}/content"
        data = json.dumps(patch_ops).encode()
        api_req = _ur.Request(url, data=data, headers={
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
        }, method="PATCH")
        with _ur.urlopen(api_req, timeout=30) as resp:
            pass  # 204 No Content on success
        return {"ok": True}
    except _ue.HTTPError as e:
        detail = e.read().decode()[:300]
        raise HTTPException(status_code=e.code, detail=detail)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/api/onenote/sections/{section_id}/pages")
async def tp_onenote_create_page(section_id: str, req: OneNoteCreatePageRequest):
    """Create a new page in a section."""
    try:
        from skills.onenote.tools import _tool_create_onenote_page
        result = _tool_create_onenote_page(section_id, req.title, req.body, req.html)
        return result
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
