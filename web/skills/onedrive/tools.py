"""OneDrive skill -- 2 tools."""
from pathlib import Path

ONEDRIVE_SKILLS_DIR = Path(__file__).parent.parent / "m365-onedrive" / "scripts"

SKILL_ID = "onedrive"
ALWAYS_ON = True

TOOL_DEFS = [
    {
        "name": "read_onedrive_file",
        "description": (
            "Download and read the text content of a file from OneDrive. "
            "Use when user asks to open, read, summarize, or extract content from a specific file. "
            "Supports .docx, .txt, .md, .csv, .xlsx, .pptx, and plain text formats. "
            "Provide either the file ID (from a previous search/list) or the file path."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "file_id": {"type": "string", "description": "OneDrive item ID (preferred if available from a prior search or list)"},
                "file_path": {"type": "string", "description": "File path relative to OneDrive root, e.g. 'Documents/report.docx'"},
                "max_chars": {"type": "integer", "description": "Max characters to return. Default 8000.", "default": 8000},
            },
            "required": [],
        },
    },
    {
        "name": "list_onedrive_files",
        "description": "List files and folders in the user's OneDrive. Use when user asks about their OneDrive, files, or documents.",
        "input_schema": {
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "Folder path to list (e.g. 'Documents/Projects'). Default: root.", "default": ""},
                "count": {"type": "integer", "description": "Max items. Default 50.", "default": 50},
            },
            "required": [],
        },
    },
    {
        "name": "search_onedrive_files",
        "description": "Search for files in OneDrive by name or content. Use when user asks to find a file.",
        "input_schema": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "Search query"},
                "count": {"type": "integer", "description": "Max results. Default 10.", "default": 10},
            },
            "required": ["query"],
        },
    },
]

TOOL_STATUS = {
    "read_onedrive_file": "\U0001f4c4 Reading file...",
    "list_onedrive_files": "\U0001f4c1 Browsing OneDrive...",
    "search_onedrive_files": "\U0001f50d Searching OneDrive...",
}


def _tool_read_onedrive_file(file_id: str = "", file_path: str = "", max_chars: int = 8000) -> dict:
    import io
    from .._m365.helpers import get_skill_client
    gc = get_skill_client(ONEDRIVE_SKILLS_DIR)

    if not file_id and not file_path:
        return {"error": "Provide file_id or file_path"}

    # Resolve item metadata — include @microsoft.graph.downloadUrl upfront.
    # This pre-authenticated URL is the most reliable way to download SharePoint-hosted
    # files (MySite, Teams files, etc.) because it bypasses the auth redirect chain.
    if file_id:
        meta_path = f"/me/drive/items/{file_id}"
    else:
        from urllib.parse import quote
        meta_path = f"/me/drive/root:/{quote(file_path.lstrip('/'))}"
    meta = gc.get(meta_path, params={"$select": "id,name,size,file,webUrl,@microsoft.graph.downloadUrl"})
    item_id = meta.get("id", file_id)
    name = meta.get("name", "")
    web_url = meta.get("webUrl", "")
    ext = name.rsplit(".", 1)[-1].lower() if "." in name else ""
    direct_url = meta.get("@microsoft.graph.downloadUrl", "")

    import httpx
    token = gc.get_token()

    # Module-level pool for file downloads (reuses TCP connections)
    global _od_dl_pool
    if not hasattr(_tool_read_onedrive_file, '_pool') or _tool_read_onedrive_file._pool.is_closed:
        _tool_read_onedrive_file._pool = httpx.Client(timeout=httpx.Timeout(60.0), follow_redirects=True)
    _pool = _tool_read_onedrive_file._pool

    def _download() -> bytes:
        # Prefer the pre-authenticated downloadUrl (no Authorization header needed).
        if direct_url:
            r = _pool.get(direct_url)
            r.raise_for_status()
            return r.content
        # Fall back to the Graph /content endpoint with Bearer token.
        dl_url = f"https://graph.microsoft.com/v1.0/me/drive/items/{item_id}/content"
        r = _pool.get(dl_url, headers={"Authorization": f"Bearer {token}"})
        r.raise_for_status()
        return r.content

    raw = _download()

    # Guard: if response looks like HTML (e.g. a login redirect that returned 200),
    # the token is wrong or the file requires different permissions.
    if raw[:5] in (b"<!DOC", b"<html", b"<HTML") or raw[:3] == b"\xef\xbb\xbf<":
        return {
            "error": "OneDrive returned an HTML page instead of the file — the token may have expired or lack Files.Read scope. Try refreshing your OneDrive token in Settings.",
            "name": name,
            "url": web_url,
            "auth_required": True,
        }

    def _docx_extract_xml(data: bytes) -> str:
        """
        Read text directly from the docx ZIP without using python-docx.
        A .docx is a ZIP containing word/document.xml — parse w:t elements directly.
        This tolerates the strict-OOXML / Word Online save format that python-docx rejects.
        """
        import zipfile
        import xml.etree.ElementTree as ET
        import re
        W = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
        try:
            with zipfile.ZipFile(io.BytesIO(data)) as z:
                with z.open("word/document.xml") as f:
                    root = ET.parse(f).getroot()
            lines = []
            for para in root.iter(f"{{{W}}}p"):
                parts = []
                for t in para.iter(f"{{{W}}}t"):
                    if t.text:
                        parts.append(t.text)
                line = "".join(parts).strip()
                if line:
                    lines.append(line)
            return "\n".join(lines)
        except Exception:
            return ""

    def _docx_extract_images(data: bytes, max_images: int = 5) -> list[dict]:
        """Extract embedded images from a docx ZIP (word/media/*)."""
        import zipfile
        import base64
        images = []
        _IMG_EXTS = {".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg",
                     ".gif": "image/gif", ".bmp": "image/bmp", ".tiff": "image/tiff"}
        try:
            with zipfile.ZipFile(io.BytesIO(data)) as z:
                media_files = sorted([n for n in z.namelist() if n.startswith("word/media/")])
                for name in media_files[:max_images]:
                    ext = "." + name.rsplit(".", 1)[-1].lower() if "." in name else ""
                    mime = _IMG_EXTS.get(ext)
                    if not mime:
                        continue
                    img_data = z.read(name)
                    if len(img_data) < 500:
                        continue  # skip tiny images (icons, bullets)
                    images.append({
                        "name": name.split("/")[-1],
                        "media_type": mime,
                        "base64": base64.b64encode(img_data).decode("ascii"),
                    })
        except Exception:
            pass
        return images

    # Extract text based on file type
    text = ""
    if ext == "docx":
        try:
            import docx
            doc = docx.Document(io.BytesIO(raw))
            text = "\n".join(p.text for p in doc.paragraphs if p.text.strip())
        except Exception:
            # python-docx uses a strict ZIP parser and rejects Word Online's extended format.
            # If the file is OLE2 (AIP/IRM-protected), fall back to server-side PDF conversion.
            if raw[:8] == b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1":
                return {
                    "error": (
                        "This file has a sensitivity label (AIP/IRM) that encrypts it. "
                        "To read it: open the file in Word desktop or Word Online → click the "
                        "Sensitivity button in the ribbon → change the label to General or remove it → save. "
                        "Then ask me to read it again."
                    ),
                    "name": name,
                    "url": web_url,
                }
            else:
                # Regular ZIP-based docx that python-docx rejected — try raw XML.
                text = _docx_extract_xml(raw)
                if not text:
                    return {
                        "error": (
                            "Could not parse the .docx file locally. "
                            "The file may be password-protected. "
                            "Open it in Word Online and paste the text here."
                        ),
                        "name": name,
                        "url": web_url,
                    }
    elif ext in ("xlsx", "xls"):
        import openpyxl
        wb = openpyxl.load_workbook(io.BytesIO(raw), read_only=True, data_only=True)
        parts = []
        for sheet in wb.worksheets:
            parts.append(f"## Sheet: {sheet.title}")
            for row in sheet.iter_rows(values_only=True):
                if any(c is not None for c in row):
                    parts.append("\t".join("" if c is None else str(c) for c in row))
        text = "\n".join(parts)
    elif ext in ("pptx",):
        from pptx import Presentation
        prs = Presentation(io.BytesIO(raw))
        parts = []
        for i, slide in enumerate(prs.slides, 1):
            parts.append(f"## Slide {i}")
            for shape in slide.shapes:
                if hasattr(shape, "text") and shape.text.strip():
                    parts.append(shape.text.strip())
        text = "\n".join(parts)
    elif ext in ("txt", "md", "csv", "json", "py", "js", "ts", "html", "xml", "yaml", "yml"):
        text = raw.decode("utf-8", errors="replace")
    else:
        # Attempt UTF-8 decode for unknown types
        try:
            text = raw.decode("utf-8", errors="strict")
        except Exception:
            return {"error": f"Cannot extract text from .{ext} files", "name": name, "url": web_url}

    truncated = len(text) > max_chars
    result = {
        "name": name,
        "url": web_url,
        "size_bytes": len(raw),
        "truncated": truncated,
        "content": text[:max_chars] + ("\n\n[... truncated ...]" if truncated else ""),
    }
    # Extract embedded images from docx so Claude can analyze them via vision
    if ext == "docx":
        images = _docx_extract_images(raw)
        print(f"[onedrive] docx image extraction: found {len(images)} images in {name}", flush=True)
        if images:
            result["_images"] = images
            result["_images_found"] = len(images)
    return result


def _tool_list_onedrive_files(path: str = "", count: int = 50) -> dict:
    from .._m365.helpers import get_skill_client
    gc = get_skill_client(ONEDRIVE_SKILLS_DIR)
    api_path = f"/me/drive/root:/{path}:/children" if path else "/me/drive/root/children"
    data = gc.get(api_path, params={"$top": str(count), "$orderby": "name",
                                     "$select": "name,size,lastModifiedDateTime,folder,file,webUrl,id"})
    items = []
    for item in data.get("value", []):
        is_folder = "folder" in item
        items.append({"name": item.get("name", ""), "type": "folder" if is_folder else "file",
                      "size": item.get("size", 0), "modified": item.get("lastModifiedDateTime", "")[:16],
                      "url": item.get("webUrl", ""), "id": item.get("id", "")})
    return {"path": path or "/", "total": len(items), "items": items}


def _tool_search_onedrive_files(query: str, count: int = 10) -> dict:
    from .._m365.helpers import get_skill_client
    gc = get_skill_client(ONEDRIVE_SKILLS_DIR)
    data = gc.get(f"/me/drive/root/search(q='{query}')",
                  params={"$top": str(count), "$select": "name,size,lastModifiedDateTime,parentReference,webUrl,id"})
    items = []
    for item in data.get("value", []):
        parent_path = item.get("parentReference", {}).get("path", "").replace("/drive/root:", "").lstrip("/")
        items.append({"name": item.get("name", ""),
                      "path": f"{parent_path}/{item.get('name','')}" if parent_path else item.get("name", ""),
                      "size": item.get("size", 0), "modified": item.get("lastModifiedDateTime", "")[:16],
                      "url": item.get("webUrl", ""), "id": item.get("id", "")})
    return {"query": query, "total": len(items), "items": items}


TOOL_HANDLERS = {
    "read_onedrive_file": _tool_read_onedrive_file,
    "list_onedrive_files": _tool_list_onedrive_files,
    "search_onedrive_files": _tool_search_onedrive_files,
}
