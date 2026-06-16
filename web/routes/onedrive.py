"""OneDrive route group -- quota, recent, shared, search, folder browsing, upload."""

import re
from pathlib import Path

from fastapi import APIRouter, HTTPException, UploadFile
from pydantic import BaseModel

import shared

ROOT = Path(__file__).parent.parent.parent

router = APIRouter()


# ── OneDrive endpoints ──────────────────────────────────────────────────────


@router.get("/api/onedrive/quota")
def onedrive_quota():
    """Return the user's OneDrive storage quota."""
    try:
        from skills._m365.helpers import get_graph_client
        gc = get_graph_client()
        drive = gc.get("/me/drive", params={"$select": "quota"})
        q = drive.get("quota", {})
        used = q.get("used", 0)
        total = q.get("total", 0)
        def _fmt(n):
            if n >= 1 << 30: return f"{n / (1 << 30):.1f} GB"
            if n >= 1 << 20: return f"{n / (1 << 20):.1f} MB"
            return f"{n / (1 << 10):.0f} KB"
        return {"used_bytes": used, "total_bytes": total,
                "used_label": _fmt(used), "total_label": _fmt(total)}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/api/onedrive/recent")
def onedrive_recent():
    """Return recently accessed files from OneDrive."""
    try:
        from skills._m365.helpers import get_graph_client
        gc = get_graph_client()
        data = gc.get("/me/drive/recent", params={
            "$top": "50",
        })
        items = data.get("value", [])
        return {"items": [
            {"id": it["id"], "name": it.get("name", ""), "is_folder": "folder" in it,
             "size": it.get("size", 0), "modified": it.get("lastModifiedDateTime", ""),
             "web_url": it.get("webUrl", ""), "mime_type": (it.get("file") or {}).get("mimeType", "")}
            for it in items if "folder" not in it
        ]}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/api/onedrive/shared")
def onedrive_shared():
    """Return files shared with the user."""
    try:
        from skills._m365.helpers import get_graph_client
        gc = get_graph_client()
        data = gc.get("/me/drive/sharedWithMe", params={
            "$select": "id,name,file,size,lastModifiedDateTime,remoteItem",
            "$top": "50",
        })
        items = data.get("value", [])
        return {"items": [
            {"id": it["id"], "name": it["name"], "is_folder": False,
             "size": it.get("remoteItem", {}).get("size", it.get("size", 0)),
             "modified": it.get("remoteItem", {}).get("lastModifiedDateTime", it.get("lastModifiedDateTime", "")),
             "web_url": it.get("remoteItem", {}).get("webUrl", it.get("webUrl", "")),
             "mime_type": it.get("remoteItem", {}).get("file", {}).get("mimeType", ""),
             "drive_id": it.get("remoteItem", {}).get("parentReference", {}).get("driveId", "")}
            for it in items
        ]}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/api/onedrive/special/{folder_name}")
def onedrive_special_folder(folder_name: str):
    """Get the drive item ID for a special folder (documents, photos, desktop)."""
    allowed = {"documents", "photos", "desktop", "music", "cameraroll"}
    if folder_name not in allowed:
        raise HTTPException(status_code=400, detail=f"Unknown special folder: {folder_name}")
    try:
        from skills._m365.helpers import get_graph_client
        gc = get_graph_client()
        item = gc.get(f"/me/drive/special/{folder_name}", params={"$select": "id,name"})
        return {"id": item["id"], "name": item["name"]}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/api/onedrive/search")
def onedrive_search(q: str = ""):
    """Search across all OneDrive files."""
    if not q.strip():
        return {"items": []}
    try:
        from skills._m365.helpers import get_graph_client
        gc = get_graph_client()
        data = gc.get(f"/me/drive/root/search(q='{q}')", params={
            "$select": "id,name,file,size,lastModifiedDateTime,webUrl",
            "$top": "50",
        })
        items = data.get("value", [])
        return {"items": [
            {"id": it["id"], "name": it["name"], "is_folder": "folder" in it,
             "size": it.get("size", 0), "modified": it.get("lastModifiedDateTime", ""),
             "web_url": it.get("webUrl", ""), "mime_type": it.get("file", {}).get("mimeType", "")}
            for it in items
        ]}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/api/onedrive/folders")
def onedrive_list_folder(parent: str = "root"):
    """List child folders (and files) of a OneDrive folder by item ID or 'root'."""
    try:
        from skills._m365.helpers import get_graph_client
        gc = get_graph_client()
        if parent == "root":
            path = "/me/drive/root/children"
        else:
            path = f"/me/drive/items/{parent}/children"
        data = gc.get(path, params={
            "$select": "id,name,folder,file,size,lastModifiedDateTime,webUrl,parentReference",
            "$orderby": "name asc",
            "$top": "200",
        })
        items = data.get("value", [])
        return {
            "items": [
                {
                    "id": it["id"],
                    "name": it["name"],
                    "is_folder": "folder" in it,
                    "has_children": it.get("folder", {}).get("childCount", 0) > 0,
                    "size": it.get("size", 0),
                    "modified": it.get("lastModifiedDateTime", ""),
                    "web_url": it.get("webUrl", ""),
                    "mime_type": it.get("file", {}).get("mimeType", ""),
                    "drive_id": it.get("parentReference", {}).get("driveId", ""),
                }
                for it in items
            ]
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/api/onedrive/items/{item_id}")
def onedrive_get_item(item_id: str, drive_id: str = ""):
    """Resolve a OneDrive item's metadata (notably its webUrl) by ID.

    Lets the front end open a pinned file that was stored without a web_url.
    Pass drive_id for SharePoint items.
    """
    if not re.match(r'^[\w.,\-!=+/]+$', item_id):
        raise HTTPException(status_code=400, detail="Invalid item_id")
    if drive_id and not re.match(r'^[\w.,\-!=+/]+$', drive_id):
        raise HTTPException(status_code=400, detail="Invalid drive_id")
    try:
        from skills._m365.helpers import get_graph_client
        gc = get_graph_client()
        path = f"/drives/{drive_id}/items/{item_id}" if drive_id else f"/me/drive/items/{item_id}"
        item = gc.get(path, params={"$select": "id,name,webUrl"})
        return {"id": item.get("id"), "name": item.get("name", ""),
                "web_url": item.get("webUrl", "")}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.delete("/api/onedrive/items/{item_id}")
def onedrive_delete_item(item_id: str, drive_id: str = ""):
    """Delete a OneDrive file or folder by item ID. Pass drive_id for SharePoint items."""
    try:
        from skills._m365.helpers import get_graph_client
        gc = get_graph_client()
        path = f"/drives/{drive_id}/items/{item_id}" if drive_id else f"/me/drive/items/{item_id}"
        gc.delete(path)
        return {"ok": True}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.patch("/api/onedrive/items/{item_id}")
def onedrive_rename_item(item_id: str, body: dict, drive_id: str = ""):
    """Rename a OneDrive file or folder. Pass drive_id for SharePoint items."""
    try:
        from skills._m365.helpers import get_graph_client
        gc = get_graph_client()
        name = (body.get("name") or "").strip()
        if not name:
            raise HTTPException(status_code=400, detail="Name cannot be empty")
        path = f"/drives/{drive_id}/items/{item_id}" if drive_id else f"/me/drive/items/{item_id}"
        result = gc.patch(path, json={"name": name})
        return {"id": result.get("id"), "name": result.get("name")}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/api/onedrive/folders/{parent_id}")
def onedrive_create_folder(parent_id: str, body: dict):
    """Create a subfolder inside a OneDrive folder."""
    try:
        from skills._m365.helpers import get_graph_client
        gc = get_graph_client()
        name = (body.get("name") or "New Folder").strip()
        if parent_id == "root":
            path = "/me/drive/root/children"
        else:
            path = f"/me/drive/items/{parent_id}/children"
        item = gc.post(path, {
            "name": name,
            "folder": {},
            "@microsoft.graph.conflictBehavior": "rename",
        })
        return {"id": item["id"], "name": item["name"]}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/api/onedrive/upload/{folder_id}")
async def onedrive_upload_to_folder(folder_id: str, file: UploadFile):
    """Upload a file to a specific OneDrive folder by item ID ('root' for root)."""
    try:
        from skills._m365.helpers import get_graph_client
        gc = get_graph_client()
        content = await file.read()
        raw_name = Path(file.filename or "attachment").name
        safe_name = re.sub(r"[^\w.\-\s]", "_", raw_name).strip() or "attachment"
        if len(safe_name) > 200:
            safe_name = safe_name[:200]
        if folder_id == "root":
            upload_path = f"/me/drive/root:/{safe_name}:/content"
        else:
            upload_path = f"/me/drive/items/{folder_id}:/{safe_name}:/content"
        item = gc.put_binary(upload_path, content, file.content_type or "application/octet-stream")
        item_id = item.get("id", "")
        if not item_id:
            raise HTTPException(status_code=500, detail="Upload failed -- no item ID returned")
        share = gc.post(f"/me/drive/items/{item_id}/createLink",
                        {"type": "view", "scope": "organization"})
        url = share.get("link", {}).get("webUrl", "")
        return {"ok": True, "id": item_id, "name": file.filename, "url": url, "size": len(content)}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/api/upload/onedrive")
async def upload_to_onedrive(file: UploadFile):
    """Upload a file to the user's OneDrive and return a shareable link."""
    try:
        from skills._m365.helpers import get_graph_client
        import urllib.parse
        gc = get_graph_client()
        content = await file.read()
        # Sanitize: strip any path components, keep only the filename,
        # then remove characters that could escape the Attachments/ folder.
        raw_name = Path(file.filename or "attachment").name
        safe_name = re.sub(r"[^\w.\-\s]", "_", raw_name).strip() or "attachment"
        if len(safe_name) > 200:
            safe_name = safe_name[:200]
        # Simple upload (< 4 MB) -- PUT to OneDrive
        item = gc.put_binary(
            f"/me/drive/root:/Attachments/{safe_name}:/content",
            content,
            file.content_type or "application/octet-stream",
        )
        item_id = item.get("id", "")
        if not item_id:
            raise HTTPException(status_code=500, detail="Upload failed -- no item ID returned")
        # Create an organisation-scoped view link
        share = gc.post(f"/me/drive/items/{item_id}/createLink",
                        {"type": "view", "scope": "organization"})
        url = share.get("link", {}).get("webUrl", "")
        return {"ok": True, "name": file.filename, "url": url, "size": len(content)}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/api/onedrive/sites")
def onedrive_list_sites():
    """List SharePoint sites the user has access to."""
    try:
        from skills._m365.helpers import get_graph_client
        gc = get_graph_client()
        data = gc.get("/sites", params={"search": "*", "$select": "id,displayName,webUrl", "$top": "50"})
        items = data.get("value", [])
        return {"sites": [{"id": s["id"], "name": s.get("displayName", ""), "web_url": s.get("webUrl", "")} for s in items]}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/api/onedrive/sites/{site_id}/drives")
def onedrive_list_site_drives(site_id: str):
    """List document libraries (drives) for a SharePoint site."""
    if not re.match(r'^[\w.,\-]+$', site_id):
        raise HTTPException(status_code=400, detail="Invalid site_id")
    try:
        from skills._m365.helpers import get_graph_client
        gc = get_graph_client()
        data = gc.get(f"/sites/{site_id}/drives", params={"$select": "id,name,webUrl", "$top": "50"})
        items = data.get("value", [])
        return {"drives": [{"id": d["id"], "name": d.get("name", ""), "web_url": d.get("webUrl", "")} for d in items]}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/api/onedrive/drives/{drive_id}/folders/{parent_id}")
def onedrive_create_folder_in_drive(drive_id: str, parent_id: str, body: dict):
    """Create a subfolder inside a SharePoint drive."""
    # SharePoint drive IDs use format "b!<base64url>" which contains '!' and '='
    if not re.match(r'^[\w.,\-!=+/]+$', drive_id):
        raise HTTPException(status_code=400, detail="Invalid drive_id")
    try:
        from skills._m365.helpers import get_graph_client
        gc = get_graph_client()
        name = (body.get("name") or "New Folder").strip()
        if parent_id == "root":
            path = f"/drives/{drive_id}/root/children"
        else:
            path = f"/drives/{drive_id}/items/{parent_id}/children"
        item = gc.post(path, {
            "name": name,
            "folder": {},
            "@microsoft.graph.conflictBehavior": "rename",
        })
        return {"id": item["id"], "name": item["name"]}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/api/onedrive/drives/{drive_id}/folders")
def onedrive_list_drive_folder(drive_id: str, parent: str = "root"):
    """List files and folders inside a SharePoint drive (by drive ID)."""
    # SharePoint drive IDs use format "b!<base64url>" which contains '!' and '='
    if not re.match(r'^[\w.,\-!=+/]+$', drive_id):
        raise HTTPException(status_code=400, detail="Invalid drive_id")
    try:
        from skills._m365.helpers import get_graph_client
        gc = get_graph_client()
        if parent == "root":
            path = f"/drives/{drive_id}/root/children"
        else:
            path = f"/drives/{drive_id}/items/{parent}/children"
        data = gc.get(path, params={
            "$select": "id,name,folder,file,size,lastModifiedDateTime,webUrl,parentReference",
            "$orderby": "name asc",
            "$top": "200",
        })
        items = data.get("value", [])
        return {
            "items": [
                {
                    "id": it["id"],
                    "name": it["name"],
                    "is_folder": "folder" in it,
                    "has_children": it.get("folder", {}).get("childCount", 0) > 0,
                    "size": it.get("size", 0),
                    "modified": it.get("lastModifiedDateTime", ""),
                    "web_url": it.get("webUrl", ""),
                    "mime_type": it.get("file", {}).get("mimeType", ""),
                    "drive_id": drive_id,
                }
                for it in items
            ]
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
