"""OneDrive skill -- 2 tools."""
from pathlib import Path

ONEDRIVE_SKILLS_DIR = Path(__file__).parent.parent / "m365-onedrive" / "scripts"

SKILL_ID = "onedrive"
ALWAYS_ON = True

TOOL_DEFS = [
    {
        "name": "read_onedrive_file",
        "description": (
            "Download and read the text content of a file from OneDrive or SharePoint. "
            "Use when user asks to open, read, summarize, or extract content from a specific file. "
            "Supports .docx, .txt, .md, .csv, .xlsx, .pptx, and plain text formats. "
            "Provide file_id (and drive_id for shared/SharePoint files), a file_path, or a SharePoint share-link URL."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "file_id": {"type": "string", "description": "OneDrive item ID (from a prior search/list or pinned file)"},
                "drive_id": {"type": "string", "description": "Drive ID for files shared with you or hosted on SharePoint. Required when the file is not on the user's own OneDrive."},
                "file_path": {"type": "string", "description": "File path relative to OneDrive root, e.g. 'Documents/report.docx'"},
                "share_url": {"type": "string", "description": "A SharePoint share-link URL (e.g. https://tenant-my.sharepoint.com/:w:/g/personal/...). Gator will resolve it to a real file via Graph."},
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
    {
        "name": "download_onedrive_file",
        "description": (
            "Download a file from OneDrive or SharePoint and save it to the local disk as raw bytes. "
            "Use when you need the actual file (e.g. to read hyperlinks from a .docx, edit a .pptx with python-pptx, "
            "or work with the file locally). Returns the local path where the file was saved. "
            "Provide file_id (and drive_id for SharePoint files), file_path, or share_url. "
            "Optionally provide local_path to control where the file is saved (default: ~/Downloads/<filename>)."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "file_id": {"type": "string", "description": "OneDrive item ID"},
                "drive_id": {"type": "string", "description": "Drive ID for SharePoint files"},
                "file_path": {"type": "string", "description": "File path relative to OneDrive root"},
                "share_url": {"type": "string", "description": "SharePoint share-link URL"},
                "local_path": {"type": "string", "description": "Where to save the file locally. Default: ~/Downloads/<filename>"},
            },
            "required": [],
        },
    },
]

TOOL_STATUS = {
    "read_onedrive_file": "\U0001f4c4 Reading file...",
    "list_onedrive_files": "\U0001f4c1 Browsing OneDrive...",
    "search_onedrive_files": "\U0001f50d Searching OneDrive...",
    "download_onedrive_file": "\U0001f4e5 Downloading file...",
}


def _tool_read_onedrive_file(file_id: str = "", drive_id: str = "", file_path: str = "", share_url: str = "", max_chars: int = 8000) -> dict:
    import io
    from .._m365.helpers import get_skill_client
    gc = get_skill_client(ONEDRIVE_SKILLS_DIR)

    if not file_id and not file_path and not share_url:
        return {"error": "Provide file_id, file_path, or share_url"}

    # Resolve SharePoint share-links via Graph /shares/{encodedUrl}/driveItem.
    # This is the only correct way — never fall back to a name search.
    if share_url:
        import base64
        encoded = base64.b64encode(share_url.encode()).decode().rstrip("=").replace("/", "_").replace("+", "-")
        share_token = f"u!{encoded}"
        try:
            resolved = gc.get(f"/shares/{share_token}/driveItem",
                              params={"$select": "id,name,parentReference"})
            file_id = resolved["id"]
            drive_id = resolved.get("parentReference", {}).get("driveId", drive_id)
        except Exception as e:
            return {
                "error": (
                    f"Could not resolve SharePoint share-link: {e}. "
                    "Please confirm the filename or paste the file content directly."
                ),
                "share_url": share_url,
                "unresolved": True,
            }

    # Resolve item metadata — include @microsoft.graph.downloadUrl upfront.
    # This pre-authenticated URL is the most reliable way to download SharePoint-hosted
    # files (MySite, Teams files, etc.) because it bypasses the auth redirect chain.
    if file_id:
        # Use /drives/{driveId}/items/{itemId} for shared/SharePoint files.
        if drive_id:
            meta_path = f"/drives/{drive_id}/items/{file_id}"
        else:
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
        if drive_id:
            dl_url = f"https://graph.microsoft.com/v1.0/drives/{drive_id}/items/{item_id}/content"
        else:
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
        W = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
        P  = f"{{{W}}}p"
        TBL = f"{{{W}}}tbl"
        TR  = f"{{{W}}}tr"
        TC  = f"{{{W}}}tc"
        T   = f"{{{W}}}t"
        try:
            with zipfile.ZipFile(io.BytesIO(data)) as z:
                with z.open("word/document.xml") as f:
                    root = ET.parse(f).getroot()
            body = root.find(f"{{{W}}}body")
            if body is None:
                return ""
            lines = []
            for child in body:
                if child.tag == P:
                    line = "".join(t.text for t in child.iter(T) if t.text).strip()
                    if line:
                        lines.append(line)
                elif child.tag == TBL:
                    rows = []
                    for tr in child.iter(TR):
                        cells = ["".join(t.text for t in tc.iter(T) if t.text).strip()
                                 for tc in tr.findall(f"{{{W}}}tc")]
                        if cells:
                            rows.append(cells)
                    if rows:
                        col_count = max(len(r) for r in rows)
                        header = "| " + " | ".join(rows[0]) + " |"
                        sep = "| " + " | ".join(["---"] * col_count) + " |"
                        body_rows = ["| " + " | ".join(r + [""] * (col_count - len(r))) + " |" for r in rows[1:]]
                        lines.append("\n".join([header, sep] + body_rows))
            return "\n".join(lines)
        except Exception:
            return ""

    def _docx_extract_hyperlinks(data: bytes) -> list[dict]:
        """Extract hyperlinks from a .docx: display text + target URL pairs.

        Reads word/_rels/document.xml.rels for relationship targets, then
        walks word/document.xml to find <w:hyperlink r:id="..."> elements and
        collects the display text of each linked run.
        Returns a list of {text, url} dicts (deduped, ordered by appearance).
        """
        import zipfile
        import xml.etree.ElementTree as ET
        W   = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
        R   = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
        HL  = f"{{{W}}}hyperlink"
        T   = f"{{{W}}}t"
        RID = f"{{{R}}}id"
        try:
            with zipfile.ZipFile(io.BytesIO(data)) as z:
                # Build rid → url map from relationships file
                rels: dict[str, str] = {}
                if "word/_rels/document.xml.rels" in z.namelist():
                    with z.open("word/_rels/document.xml.rels") as f:
                        rels_root = ET.parse(f).getroot()
                    for rel in rels_root:
                        rid = rel.attrib.get("Id", "")
                        target = rel.attrib.get("Target", "")
                        typ = rel.attrib.get("Type", "")
                        if "hyperlink" in typ and target:
                            rels[rid] = target
                if not rels:
                    return []
                # Walk document.xml for <w:hyperlink r:id="..."> elements
                with z.open("word/document.xml") as f:
                    doc_root = ET.parse(f).getroot()
            seen: dict[str, str] = {}  # url → first display text
            results: list[dict] = []
            for hl in doc_root.iter(HL):
                rid = hl.attrib.get(RID, "")
                if not rid or rid not in rels:
                    continue
                url = rels[rid]
                text = "".join(t.text for t in hl.iter(T) if t.text).strip()
                if not text:
                    text = url
                if url not in seen:
                    seen[url] = text
                    results.append({"text": text, "url": url})
            return results
        except Exception:
            return []

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
            parts = []
            # Walk body children in document order so tables appear inline with paragraphs
            for block in doc.element.body:
                tag = block.tag.split("}")[-1] if "}" in block.tag else block.tag
                if tag == "p":
                    from docx.oxml.ns import qn
                    text_parts = [t.text for t in block.iter(qn("w:t")) if t.text]
                    line = "".join(text_parts).strip()
                    if line:
                        parts.append(line)
                elif tag == "tbl":
                    from docx.oxml.ns import qn
                    rows = []
                    for tr in block.iter(qn("w:tr")):
                        cells = []
                        for tc in tr.iter(qn("w:tc")):
                            cell_parts = [t.text for t in tc.iter(qn("w:t")) if t.text]
                            cells.append("".join(cell_parts).strip())
                        if cells:
                            rows.append(cells)
                    if rows:
                        col_count = max(len(r) for r in rows)
                        header = "| " + " | ".join(rows[0]) + " |"
                        sep = "| " + " | ".join(["---"] * col_count) + " |"
                        body_rows = ["| " + " | ".join(r + [""] * (col_count - len(r))) + " |" for r in rows[1:]]
                        parts.append("\n".join([header, sep] + body_rows))
            text = "\n".join(parts)
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
    # Extract embedded images and hyperlinks from docx
    if ext == "docx":
        images = _docx_extract_images(raw)
        print(f"[onedrive] docx image extraction: found {len(images)} images in {name}", flush=True)
        if images:
            result["_images"] = images
            result["_images_found"] = len(images)
        hyperlinks = _docx_extract_hyperlinks(raw)
        if hyperlinks:
            result["hyperlinks"] = hyperlinks
            print(f"[onedrive] docx hyperlink extraction: found {len(hyperlinks)} links in {name}", flush=True)
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


def _tool_download_onedrive_file(file_id: str = "", drive_id: str = "", file_path: str = "", share_url: str = "", local_path: str = "") -> dict:
    """Download a OneDrive/SharePoint file and save it to disk as raw bytes.
    Returns the local path where the file was saved."""
    import io as _io
    from .._m365.helpers import get_skill_client
    import httpx as _httpx
    gc = get_skill_client(ONEDRIVE_SKILLS_DIR)

    if not file_id and not file_path and not share_url:
        return {"error": "Provide file_id, file_path, or share_url"}

    # Resolve share URL
    if share_url:
        import base64
        encoded = base64.b64encode(share_url.encode()).decode().rstrip("=").replace("/", "_").replace("+", "-")
        share_token = f"u!{encoded}"
        try:
            resolved = gc.get(f"/shares/{share_token}/driveItem",
                              params={"$select": "id,name,parentReference"})
            file_id = resolved["id"]
            drive_id = resolved.get("parentReference", {}).get("driveId", drive_id)
        except Exception as e:
            return {"error": f"Could not resolve share URL: {e}"}

    # Get metadata + pre-authenticated download URL
    if file_id:
        meta_path = f"/drives/{drive_id}/items/{file_id}" if drive_id else f"/me/drive/items/{file_id}"
    else:
        from urllib.parse import quote
        meta_path = f"/me/drive/root:/{quote(file_path.lstrip('/'))}"
    meta = gc.get(meta_path, params={"$select": "id,name,size,@microsoft.graph.downloadUrl"})
    name = meta.get("name", "file")
    direct_url = meta.get("@microsoft.graph.downloadUrl", "")
    item_id = meta.get("id", file_id)

    # Download bytes
    pool = _httpx.Client(timeout=_httpx.Timeout(120.0), follow_redirects=True)
    try:
        if direct_url:
            r = pool.get(direct_url)
        else:
            dl_url = f"https://graph.microsoft.com/v1.0/drives/{drive_id}/items/{item_id}/content" if drive_id \
                     else f"https://graph.microsoft.com/v1.0/me/drive/items/{item_id}/content"
            r = pool.get(dl_url, headers={"Authorization": f"Bearer {gc.get_token()}"})
        r.raise_for_status()
        raw = r.content
    finally:
        pool.close()

    if raw[:5] in (b"<!DOC", b"<html", b"<HTML"):
        return {"error": "Got HTML instead of file bytes — token may have expired"}

    # Determine save path
    from pathlib import Path as _Path
    if local_path:
        dest = _Path(local_path).expanduser()
    else:
        dest = _Path.home() / "Downloads" / name
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_bytes(raw)
    return {"saved_to": str(dest), "name": name, "size_bytes": len(raw)}


TOOL_HANDLERS = {
    "read_onedrive_file": _tool_read_onedrive_file,
    "list_onedrive_files": _tool_list_onedrive_files,
    "search_onedrive_files": _tool_search_onedrive_files,
    "download_onedrive_file": _tool_download_onedrive_file,
}
