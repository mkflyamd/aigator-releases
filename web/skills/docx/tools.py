"""Word/DOCX skill -- 4 tools."""

import os
import re
import tempfile
import contextlib

SKILL_ID = "docx"
SKILL_ALIASES = ["docx_skill"]

TOOL_DEFS = [
    {
        "name": "get_docx_info",
        "description": "Get structural info about a Word document: paragraph count, table count, heading outline, styles used, and metadata (author, title, dates). Use this first to understand a document before reading or editing. Use file_path='open' for the currently open Word document via COM.",
        "input_schema": {
            "type": "object",
            "properties": {
                "file_path": {"type": "string", "description": "Full path to .docx file, OneDrive item ID (from search_onedrive_files or list_onedrive_files), or 'open' / 'open:Report.docx' for the active Word document via COM. OneDrive item IDs are automatically downloaded, edited, and re-uploaded."},
            },
            "required": ["file_path"],
        },
    },
    {
        "name": "read_docx",
        "description": "Read content from a Word document. Returns paragraphs with their style (heading level, list type), and optionally tables. Use file_path='open' for the currently open Word document via COM, or provide a full file path. Use content_type to select what to read.",
        "input_schema": {
            "type": "object",
            "properties": {
                "file_path": {"type": "string", "description": "Full path to .docx file, OneDrive item ID (from search_onedrive_files or list_onedrive_files), or 'open' / 'open:Report.docx' for the active Word document via COM. OneDrive item IDs are automatically downloaded, edited, and re-uploaded."},
                "content_type": {"type": "string", "enum": ["all", "paragraphs", "tables", "headings"], "description": "What to read: 'all' for everything, 'paragraphs' for text only, 'tables' for tables only, 'headings' for heading outline. Defaults to 'all'.", "default": "all"},
                "max_paragraphs": {"type": "integer", "description": "Maximum paragraphs to return. Defaults to 200.", "default": 200},
            },
            "required": ["file_path"],
        },
    },
    {
        "name": "create_docx",
        "description": "Create a professional Word document (.docx) with rich formatting. Supports headings, paragraphs, bullets, numbered lists, tables with formatting, images, hyperlinks, footnotes, page breaks, table of contents, headers/footers with page numbers, and multi-column layouts. For inline formatting use 'runs' array instead of 'text'. Call once with all content.",
        "input_schema": {
            "type": "object",
            "properties": {
                "file_path": {"type": "string", "description": "Full path where the .docx file will be saved"},
                "title": {"type": "string", "description": "Document title (added as Title style at the top). Optional.", "default": ""},
                "author": {"type": "string", "description": "Document author metadata. Optional.", "default": ""},
                "page_size": {"type": "string", "enum": ["letter", "a4"], "description": "Page size. Defaults to 'letter'.", "default": "letter"},
                "orientation": {"type": "string", "enum": ["portrait", "landscape"], "description": "Page orientation. Defaults to 'portrait'.", "default": "portrait"},
                "margins": {"type": "object", "description": "Page margins in inches. Keys: top, bottom, left, right. Defaults to 1.0 inch each.", "properties": {"top": {"type": "number"}, "bottom": {"type": "number"}, "left": {"type": "number"}, "right": {"type": "number"}}},
                "header_text": {"type": "string", "description": "Header text shown on every page. Optional.", "default": ""},
                "footer_text": {"type": "string", "description": "Footer text. Use {{page}} for page number, e.g. 'Page {{page}}'. Optional.", "default": ""},
                "columns": {"type": "integer", "description": "Number of columns (1-3). Defaults to 1.", "default": 1},
                "footnotes": {
                    "type": "array",
                    "description": "Footnote definitions. Reference by id in content runs via {\"footnote\": id}.",
                    "items": {"type": "object", "properties": {"id": {"type": "integer"}, "text": {"type": "string"}}, "required": ["id", "text"]},
                },
                "content": {
                    "type": "array",
                    "description": "Ordered list of content blocks.",
                    "items": {
                        "type": "object",
                        "properties": {
                            "type": {"type": "string", "enum": ["heading1", "heading2", "heading3", "paragraph", "bullet", "numbered", "table", "page_break", "toc", "image", "hyperlink"], "description": "Block type"},
                            "text": {"type": "string", "description": "Plain text content (for heading, paragraph, bullet, numbered, hyperlink)"},
                            "runs": {
                                "type": "array",
                                "description": "Rich inline content instead of plain text. Each run can have formatting.",
                                "items": {
                                    "type": "object",
                                    "properties": {
                                        "text": {"type": "string", "description": "Run text"},
                                        "bold": {"type": "boolean"}, "italic": {"type": "boolean"}, "underline": {"type": "boolean"},
                                        "color": {"type": "string", "description": "Hex color e.g. 'FF0000' for red"},
                                        "size": {"type": "integer", "description": "Font size in points"},
                                        "font": {"type": "string", "description": "Font name e.g. 'Times New Roman'"},
                                        "footnote": {"type": "integer", "description": "Footnote id to insert reference"},
                                    },
                                },
                            },
                            "rows": {"type": "array", "description": "Table rows as 2D array. First row is header.", "items": {"type": "array", "items": {"type": "string"}}},
                            "path": {"type": "string", "description": "Image file path (for type 'image')"},
                            "width": {"type": "number", "description": "Image width in inches (for type 'image'). Defaults to 4.0.", "default": 4.0},
                            "url": {"type": "string", "description": "URL for hyperlink (for type 'hyperlink')"},
                            "bold": {"type": "boolean", "description": "Bold the entire block text"},
                            "italic": {"type": "boolean", "description": "Italicize the entire block text"},
                            "alignment": {"type": "string", "enum": ["left", "center", "right", "justify"], "description": "Paragraph alignment"},
                        },
                        "required": ["type"],
                    },
                },
            },
            "required": ["file_path", "content"],
        },
    },
    {
        "name": "update_docx",
        "description": "Update an existing Word document. Supports single operations or batch mode for multiple edits in one call. ALWAYS use batch mode when making more than one change. Use file_path='open' for COM, or provide a full file path. IMPORTANT: For insert_after/find_replace, find_text must exactly match text in the document — call read_docx first to get the exact paragraph text, then use a substring of that as find_text. If the update returns 'Could not find paragraph', do NOT silently switch to another platform — report the failure and ask the user how to proceed.",
        "input_schema": {
            "type": "object",
            "properties": {
                "file_path": {"type": "string", "description": "Full path to .docx file, OneDrive item ID (from search_onedrive_files or list_onedrive_files), or 'open' / 'open:Report.docx' for the active Word document via COM. OneDrive item IDs are automatically downloaded, edited, and re-uploaded."},
                "action": {"type": "string", "enum": ["find_replace", "append", "insert_after", "table_update", "introspect_table", "check_checkbox", "batch"], "description": "Action to perform. Use 'introspect_table' first on any unknown document to see row/col layout, merge state, and checkbox types. Use 'table_update' to write text to cells (merge-safe). Use 'check_checkbox' to toggle form checkboxes. Use 'batch' to combine multiple operations."},
                "find_text": {"type": "string", "description": "Text to search for (used by find_replace and insert_after)", "default": ""},
                "replace_text": {"type": "string", "description": "Replacement text (for find_replace only)", "default": ""},
                "content_type": {"type": "string", "enum": ["paragraph", "heading1", "heading2", "heading3", "bullet"], "description": "Type of content to add (for append and insert_after). Defaults to 'paragraph'.", "default": "paragraph"},
                "text": {"type": "string", "description": "Text content to add (for append and insert_after)", "default": ""},
                "table_index": {"type": "integer", "description": "0-based index of the table in the document (for table_update action). Defaults to 0.", "default": 0},
                "cells": {
                    "type": "array",
                    "description": "For table_update: array of {row, col, text}. For check_checkbox: array of {row, col, checked}. Row/col are 0-based and match introspect_table output.",
                    "items": {
                        "type": "object",
                        "properties": {
                            "row": {"type": "integer", "description": "0-based row index"},
                            "col": {"type": "integer", "description": "0-based column index"},
                            "text": {"type": "string", "description": "New cell text (for table_update)"},
                            "checked": {"type": "boolean", "description": "true=check, false=uncheck (for check_checkbox)"},
                        },
                        "required": ["row", "col"],
                    },
                },
                "operations": {
                    "type": "array",
                    "description": "For batch mode: array of operations. Each operation has action, and relevant fields (find_text, replace_text, content_type, text, table_index, cells).",
                    "items": {
                        "type": "object",
                        "properties": {
                            "action": {"type": "string", "enum": ["find_replace", "append", "insert_after", "table_update", "check_checkbox"]},
                            "find_text": {"type": "string"}, "replace_text": {"type": "string"},
                            "content_type": {"type": "string", "enum": ["paragraph", "heading1", "heading2", "heading3", "bullet"]},
                            "text": {"type": "string"},
                            "table_index": {"type": "integer"},
                            "cells": {"type": "array", "items": {"type": "object", "properties": {"row": {"type": "integer"}, "col": {"type": "integer"}, "text": {"type": "string"}}, "required": ["row", "col", "text"]}},
                        },
                        "required": ["action"],
                    },
                },
            },
            "required": ["file_path", "action"],
        },
    },
]

TOOL_STATUS = {
    "get_docx_info": "\U0001f4c4 Inspecting Word document...",
    "read_docx":     "\U0001f4c4 Reading Word document...",
    "create_docx":   "\U0001f4dd Creating Word document...",
    "update_docx":   "\u270f\ufe0f Updating Word document...",
}

# ── XML namespace helper (imported from docx at call time to avoid circular imports) ──
def _get_qn():
    from docx.oxml.ns import qn
    return qn


# ── Helpers ──────────────────────────────────────────────────────────────────

def _heading_level(style_name: str):
    """Extract heading level from style name, e.g. 'Heading 1' -> 1. Returns None for non-headings."""
    m = re.match(r"Heading\s*(\d+)", style_name or "")
    return int(m.group(1)) if m else None


def _com_style_name(para) -> str:
    """Safely retrieve the style name for a Word COM paragraph."""
    try:
        style = getattr(para, "Style", None)
        if style is None:
            return ""
        return getattr(style, "NameLocal", None) or getattr(style, "Name", None) or ""
    except Exception:
        return ""


def _py_style_name(para) -> str:
    """Safely retrieve the style name for a python-docx paragraph."""
    try:
        style = getattr(para, "style", None)
        if style is None:
            return ""
        return getattr(style, "name", None) or ""
    except Exception:
        return ""


def _get_row_col_elements(tr, qn_fn):
    """
    Return ordered list of (kind, element) for each logical column in a row.
    Handles both plain <w:tc> and <w:sdt>-wrapped <w:tc> (e.g. PERM-style checkbox cells).
    kind is 'tc' or 'sdt'.
    """
    cols = []
    for child in tr:
        local = child.tag.split('}')[-1] if '}' in child.tag else child.tag
        if local == 'tc':
            cols.append(('tc', child))
        elif local == 'sdt':
            if child.find('.//' + qn_fn('w:tc')) is not None:
                cols.append(('sdt', child))
    return cols


def _safe_write_cell(cell, text: str):
    """
    Write text to a cell without touching <w:tcPr>.
    Preserves merge state (gridSpan, vMerge), borders, shading.
    """
    for para in cell.paragraphs:
        for run in para.runs:
            run.text = ''
    if cell.paragraphs and cell.paragraphs[0].runs:
        cell.paragraphs[0].runs[0].text = text
    else:
        cell.paragraphs[0].add_run(text)


def _toggle_sdt_checkbox(sdt_el, check: bool, qn_fn):
    """Toggle a content-control (<w:sdt> + <w14:checkbox>) element."""
    target = '\u2611' if check else '\u2610'
    checked_el = sdt_el.find('.//' + qn_fn('w14:checked'))
    if checked_el is not None:
        checked_el.set(qn_fn('w14:val'), '1' if check else '0')
    for t in sdt_el.findall('.//' + qn_fn('w:t')):
        if t.text in ('\u2610', '\u2611', '\u2612'):
            t.text = target


def _toggle_checkbox_in_tc(tc_el, check: bool, qn_fn):
    """Toggle checkboxes inside a plain <w:tc> element (SDTs or unicode runs)."""
    target = '\u2611' if check else '\u2610'
    toggled = False
    for sdt in tc_el.iter(qn_fn('w:sdt')):
        if sdt.find('.//' + qn_fn('w14:checkbox')) is not None:
            _toggle_sdt_checkbox(sdt, check, qn_fn)
            toggled = True
    if not toggled:
        for t in tc_el.iter(qn_fn('w:t')):
            if t.text and any(ch in t.text for ch in ('\u2610', '\u2611', '\u2612')):
                t.text = (t.text.replace('\u2610', target)
                                .replace('\u2611', target)
                                .replace('\u2612', target))


def _is_vmerge_continuation(cell, qn_fn):
    tcPr = cell._tc.find(qn_fn('w:tcPr'))
    if tcPr is None:
        return False
    vMerge = tcPr.find(qn_fn('w:vMerge'))
    return vMerge is not None and vMerge.get(qn_fn('w:val')) is None


def _replace_in_paragraph(paragraph, find_text: str, replace_text: str) -> bool:
    """Replace text across runs within a paragraph. Returns True if replaced."""
    full_text = "".join(run.text for run in paragraph.runs)
    if find_text not in full_text:
        return False
    new_text = full_text.replace(find_text, replace_text)
    for i, run in enumerate(paragraph.runs):
        if i == 0:
            run.text = new_text
        else:
            run.text = ""
    return True


# ── OneDrive download / upload helper ────────────────────────────────────────

class _OneDriveLocked(Exception):
    """Raised when OneDrive returns 423 — file is open/locked in Word."""
    def __init__(self, filename: str):
        self.filename = filename
        super().__init__(f"423 Locked: {filename}")

def _is_onedrive_ref(file_path: str) -> bool:
    """True if file_path is a OneDrive item ID or onedrive:// URI — not a local path."""
    if not file_path:
        return False
    if file_path.startswith("onedrive://"):
        return True
    # Graph item IDs are opaque alphanumeric strings, typically 20-40 chars,
    # with no path separators, dots, or spaces.
    if (20 <= len(file_path) <= 60
            and "\\" not in file_path
            and "/" not in file_path
            and "." not in file_path
            and " " not in file_path
            and not file_path.startswith("open")):
        return True
    return False


def _parse_onedrive_ref(file_path: str) -> str:
    """Extract the Graph item ID from a onedrive:// URI or bare ID."""
    if file_path.startswith("onedrive://"):
        return file_path[len("onedrive://"):]
    return file_path


@contextlib.contextmanager
def _onedrive_docx_context(item_id: str, readonly: bool = False):
    """Download a .docx from OneDrive to a temp file, yield (local_path, name),
    then upload the modified file back.  On readonly=True, skip the upload."""
    import time as _time
    import httpx
    from pathlib import Path
    from .._m365.helpers import get_skill_client

    ONEDRIVE_SKILLS_DIR = Path(__file__).parent.parent / "m365-onedrive" / "scripts"
    gc = get_skill_client(ONEDRIVE_SKILLS_DIR)

    # Resolve metadata to get the pre-auth downloadUrl and filename
    meta = gc.get(f"/me/drive/items/{item_id}",
                  params={"$select": "id,name,@microsoft.graph.downloadUrl"})
    name = meta.get("name", "document.docx")
    direct_url = meta.get("@microsoft.graph.downloadUrl", "")
    token = gc.get_token()

    # Download
    client = httpx.Client(timeout=httpx.Timeout(60.0), follow_redirects=True)
    try:
        if direct_url:
            r = client.get(direct_url)
        else:
            r = client.get(
                f"https://graph.microsoft.com/v1.0/me/drive/items/{item_id}/content",
                headers={"Authorization": f"Bearer {token}"},
            )
        r.raise_for_status()
        raw = r.content
    finally:
        client.close()

    if raw[:5] in (b"<!DOC", b"<html", b"<HTML"):
        raise RuntimeError("OneDrive returned an HTML page instead of the file — token may have expired.")

    # Write to temp file
    suffix = f"_{name}" if name.endswith(".docx") else "_document.docx"
    tmp = tempfile.NamedTemporaryFile(suffix=suffix, delete=False)
    tmp.write(raw)
    tmp.close()
    local_path = tmp.name

    try:
        yield local_path, name

        if not readonly:
            # Upload modified file back to OneDrive
            with open(local_path, "rb") as fh:
                updated = fh.read()

            # Use upload session — required for shared/co-authored files
            # (direct PUT returns 423 on SharePoint-backed OneDrive when file is shared)
            sess_client = httpx.Client(timeout=httpx.Timeout(30.0), follow_redirects=True)
            try:
                sess_resp = sess_client.post(
                    f"https://graph.microsoft.com/v1.0/me/drive/items/{item_id}/createUploadSession",
                    headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
                    json={"item": {"@microsoft.graph.conflictBehavior": "replace"}},
                )
            finally:
                sess_client.close()

            if sess_resp.is_success:
                upload_url = sess_resp.json().get("uploadUrl", "")
                size = len(updated)
                up_client = httpx.Client(timeout=httpx.Timeout(120.0), follow_redirects=True)
                try:
                    resp = up_client.put(
                        upload_url,
                        headers={
                            "Content-Range": f"bytes 0-{size - 1}/{size}",
                            "Content-Length": str(size),
                        },
                        content=updated,
                    )
                finally:
                    up_client.close()
            else:
                # Session creation failed — fall back to direct PUT
                put_client = httpx.Client(timeout=httpx.Timeout(120.0), follow_redirects=True)
                try:
                    resp = put_client.put(
                        f"https://graph.microsoft.com/v1.0/me/drive/items/{item_id}/content",
                        headers={"Authorization": f"Bearer {token}", "Content-Type": "application/octet-stream"},
                        content=updated,
                    )
                finally:
                    put_client.close()

            if resp.status_code == 423:
                raise _OneDriveLocked(name)
            resp.raise_for_status()
    finally:
        try:
            os.unlink(local_path)
        except OSError:
            pass


# ── Tool Handlers ────────────────────────────────────────────────────────────

def _tool_get_docx_info(file_path: str) -> dict:
    if _is_onedrive_ref(file_path):
        try:
            with _onedrive_docx_context(_parse_onedrive_ref(file_path), readonly=True) as (local, name):
                result = _tool_get_docx_info(local)
                result["file"] = f"OneDrive: {name}"
                return result
        except _OneDriveLocked as locked:
            result = _tool_get_docx_info(f"open:{locked.filename}")
            result["_via"] = "COM fallback (file was open in Word)"
            return result
        except Exception as ex:
            return {"error": f"OneDrive download failed: {ex}"}
    try:
        if file_path.startswith("open"):
            from skills._office_com import get_word_app, get_word_document, list_word_documents
            word, err = get_word_app()
            if err:
                return {"error": err}
            doc, err = get_word_document(word, file_path)
            if err:
                return {"error": err}
            para_count = doc.Paragraphs.Count
            table_count = doc.Tables.Count
            section_count = doc.Sections.Count

            outline = []
            styles_used = set()
            for i in range(1, para_count + 1):
                para = doc.Paragraphs(i)
                style_name = _com_style_name(para)
                styles_used.add(style_name)
                level = _heading_level(style_name)
                if level is not None:
                    outline.append({"level": level, "text": para.Range.Text.rstrip("\r")})

            metadata = {}
            try:
                props = doc.BuiltInDocumentProperties
                metadata["author"] = str(props("Author"))
                metadata["title"] = str(props("Title"))
                metadata["created"] = str(props("Creation Date"))
                metadata["modified"] = str(props("Last Save Time"))
            except Exception:
                pass

            return {
                "ok": True, "file": doc.FullName,
                "paragraph_count": para_count, "table_count": table_count,
                "section_count": section_count,
                "heading_outline": outline,
                "metadata": metadata,
                "styles_used": sorted(styles_used),
            }
        else:
            from docx import Document
            doc = Document(file_path)
            para_count = len(doc.paragraphs)
            table_count = len(doc.tables)
            section_count = len(doc.sections)

            outline = []
            styles_used = set()
            for para in doc.paragraphs:
                sname = _py_style_name(para)
                styles_used.add(sname)
                level = _heading_level(sname)
                if level is not None:
                    outline.append({"level": level, "text": para.text})

            metadata = {}
            try:
                cp = doc.core_properties
                metadata["author"] = cp.author or ""
                metadata["title"] = cp.title or ""
                metadata["created"] = str(cp.created) if cp.created else ""
                metadata["modified"] = str(cp.modified) if cp.modified else ""
            except Exception:
                pass

            return {
                "ok": True, "file": file_path,
                "paragraph_count": para_count, "table_count": table_count,
                "section_count": section_count,
                "heading_outline": outline,
                "metadata": metadata,
                "styles_used": sorted(styles_used),
            }
    except Exception as e:
        return {"error": str(e)}


def _tool_read_docx(file_path: str, content_type: str = "all", max_paragraphs: int = 200) -> dict:
    if _is_onedrive_ref(file_path):
        try:
            with _onedrive_docx_context(_parse_onedrive_ref(file_path), readonly=True) as (local, name):
                result = _tool_read_docx(local, content_type=content_type, max_paragraphs=max_paragraphs)
                result["file"] = f"OneDrive: {name}"
                return result
        except _OneDriveLocked as locked:
            result = _tool_read_docx(f"open:{locked.filename}", content_type=content_type, max_paragraphs=max_paragraphs)
            result["_via"] = "COM fallback (file was open in Word)"
            return result
        except Exception as ex:
            return {"error": f"OneDrive download failed: {ex}"}
    try:
        if file_path.startswith("open"):
            from skills._office_com import get_word_app, get_word_document
            word, err = get_word_app()
            if err:
                return {"error": err}
            doc, err = get_word_document(word, file_path)
            if err:
                return {"error": err}

            paragraphs = []
            tables = []
            want_paras = content_type in ("all", "paragraphs", "headings")
            want_tables = content_type in ("all", "tables")

            if want_paras:
                total = doc.Paragraphs.Count
                limit = min(total, max_paragraphs)
                for i in range(1, limit + 1):
                    para = doc.Paragraphs(i)
                    style_name = _com_style_name(para)
                    level = _heading_level(style_name)
                    if content_type == "headings" and level is None:
                        continue
                    paragraphs.append({
                        "index": i - 1,
                        "text": para.Range.Text.rstrip("\r"),
                        "style": style_name,
                        "heading_level": level,
                    })

            if want_tables:
                for t in range(1, doc.Tables.Count + 1):
                    table = doc.Tables(t)
                    rows = []
                    for r in range(1, table.Rows.Count + 1):
                        row = []
                        for c in range(1, table.Columns.Count + 1):
                            try:
                                row.append(table.Cell(r, c).Range.Text.rstrip("\r\x07"))
                            except Exception:
                                row.append("")
                        rows.append(row)
                    tables.append({"index": t - 1, "rows": rows})

            result = {"ok": True, "file": doc.FullName, "truncated": doc.Paragraphs.Count > max_paragraphs}
            if want_paras:
                result["paragraphs"] = paragraphs
            if want_tables:
                result["tables"] = tables
            return result
        else:
            from docx import Document
            doc = Document(file_path)

            paragraphs = []
            tables = []
            want_paras = content_type in ("all", "paragraphs", "headings")
            want_tables = content_type in ("all", "tables")

            if want_paras:
                for idx, para in enumerate(doc.paragraphs):
                    if idx >= max_paragraphs:
                        break
                    sname = _py_style_name(para)
                    level = _heading_level(sname)
                    if content_type == "headings" and level is None:
                        continue
                    paragraphs.append({
                        "index": idx,
                        "text": para.text,
                        "style": sname,
                        "heading_level": level,
                    })

            if want_tables:
                for idx, table in enumerate(doc.tables):
                    rows = []
                    for row in table.rows:
                        rows.append([cell.text for cell in row.cells])
                    tables.append({"index": idx, "rows": rows})

            result = {"ok": True, "file": file_path, "truncated": len(doc.paragraphs) > max_paragraphs}
            if want_paras:
                result["paragraphs"] = paragraphs
            if want_tables:
                result["tables"] = tables
            return result
    except Exception as e:
        return {"error": str(e)}


def _tool_create_docx(file_path: str, content: list, title: str = "", author: str = "",
                       page_size: str = "letter", orientation: str = "portrait",
                       margins: dict = None, header_text: str = "", footer_text: str = "",
                       columns: int = 1, footnotes: list = None) -> dict:
    try:
        from docx import Document
        from docx.shared import Pt, Inches
        from docx.enum.text import WD_ALIGN_PARAGRAPH
        from .helpers import (
            set_page_layout, setup_styles, add_header, add_footer,
            set_columns, add_toc, add_hyperlink, add_footnotes_part,
            add_footnote_ref, format_table, apply_run_format, validate_docx,
        )

        doc = Document()

        # ── Document setup ──
        setup_styles(doc)
        section = doc.sections[0]
        set_page_layout(section, page_size, orientation, margins)

        if header_text:
            add_header(section, header_text)
        if footer_text:
            add_footer(section, footer_text)
        if columns > 1:
            set_columns(section, columns)

        if author:
            doc.core_properties.author = author

        # ── Footnotes part (must be created before content references them) ──
        if footnotes:
            add_footnotes_part(doc, footnotes)

        # ── Title ──
        if title:
            doc.add_heading(title, level=0)

        # ── Alignment map ──
        align_map = {
            "left": WD_ALIGN_PARAGRAPH.LEFT,
            "center": WD_ALIGN_PARAGRAPH.CENTER,
            "right": WD_ALIGN_PARAGRAPH.RIGHT,
            "justify": WD_ALIGN_PARAGRAPH.JUSTIFY,
        }

        para_count = 0
        table_count = 0
        image_count = 0

        for block in content:
            if isinstance(block, str):
                block = {"type": "paragraph", "text": block}
            if not isinstance(block, dict):
                continue
            btype = block.get("type", "paragraph")
            text = block.get("text", "")
            runs_data = block.get("runs")
            rows = block.get("rows")
            alignment = block.get("alignment")

            # ── Headings ──
            if btype in ("heading1", "heading2", "heading3"):
                level = int(btype[-1])
                p = doc.add_heading(text, level=level)
                if alignment:
                    p.alignment = align_map.get(alignment)
                para_count += 1

            # ── Paragraph / Bullet / Numbered ──
            elif btype in ("paragraph", "bullet", "numbered"):
                style = {"paragraph": None, "bullet": "List Bullet", "numbered": "List Number"}.get(btype)
                p = doc.add_paragraph(style=style)
                if alignment:
                    p.alignment = align_map.get(alignment)

                if runs_data:
                    _add_runs(p, runs_data)
                else:
                    run = p.add_run(text)
                    if block.get("bold"):
                        run.font.bold = True
                    if block.get("italic"):
                        run.font.italic = True
                para_count += 1

            # ── Table ──
            elif btype == "table" and rows:
                if not rows or not rows[0]:
                    continue
                tbl = doc.add_table(rows=len(rows), cols=len(rows[0]))
                tbl.style = "Table Grid"
                for r_idx, row in enumerate(rows):
                    for c_idx, cell_text in enumerate(row):
                        tbl.cell(r_idx, c_idx).text = str(cell_text)
                format_table(tbl)
                table_count += 1

            # ── Page Break ──
            elif btype == "page_break":
                doc.add_page_break()

            # ── Table of Contents ──
            elif btype == "toc":
                add_toc(doc)
                para_count += 1

            # ── Image ──
            elif btype == "image":
                img_path = block.get("path", "")
                width = block.get("width", 4.0)
                if img_path and os.path.exists(img_path):
                    doc.add_picture(img_path, width=Inches(width))
                    image_count += 1

            # ── Hyperlink ──
            elif btype == "hyperlink":
                url = block.get("url", "")
                p = doc.add_paragraph()
                if alignment:
                    p.alignment = align_map.get(alignment)
                if url:
                    add_hyperlink(p, url, text or url)
                else:
                    p.add_run(text)
                para_count += 1

        doc.save(file_path)

        # ── Validation ──
        valid, validation_msg = validate_docx(file_path)

        result = {
            "ok": True,
            "message": f"Created {file_path}",
            "file_path": file_path,
            "paragraph_count": para_count,
            "table_count": table_count,
            "image_count": image_count,
        }
        if not valid:
            result["validation_warning"] = validation_msg
        return result
    except Exception as e:
        return {"error": str(e)}


def _add_runs(paragraph, runs_data):
    """Add formatted runs (including footnote refs) to a paragraph."""
    from .helpers import apply_run_format, add_footnote_ref

    for rd in runs_data:
        if "footnote" in rd:
            add_footnote_ref(paragraph, rd["footnote"])
        elif "text" in rd:
            run = paragraph.add_run(rd["text"])
            apply_run_format(
                run,
                bold=rd.get("bold"),
                italic=rd.get("italic"),
                underline=rd.get("underline"),
                color=rd.get("color"),
                size=rd.get("size"),
                font=rd.get("font"),
            )


def _tool_update_docx(file_path: str, action: str, find_text: str = "",
                       replace_text: str = "", content_type: str = "paragraph",
                       text: str = "", table_index: int = 0,
                       cells: list = None, operations: list = None) -> dict:
    if _is_onedrive_ref(file_path):
        try:
            item_id = _parse_onedrive_ref(file_path)
            with _onedrive_docx_context(item_id, readonly=False) as (local, name):
                result = _tool_update_docx(
                    local, action, find_text=find_text, replace_text=replace_text,
                    content_type=content_type, text=text, table_index=table_index,
                    cells=cells, operations=operations,
                )
            if result.get("ok"):
                result["file"] = f"OneDrive: {name}"
                result["message"] = result.get("message", "") + " (saved to OneDrive)"
            return result
        except _OneDriveLocked as locked:
            # File is locked — try COM fallback only if Word is actually running
            try:
                from skills._office_com import get_word_app
                word, err = get_word_app()
                word_available = (err is None and word is not None)
            except Exception:
                word_available = False

            if not word_available:
                return {
                    "error": (
                        f"'{locked.filename}' is exclusively checked out in Word by someone — "
                        "the upload session could not acquire a lock. "
                        "Ask the other user to close the file, or try again in a few minutes."
                    )
                }

            result = _tool_update_docx(
                f"open:{locked.filename}", action, find_text=find_text, replace_text=replace_text,
                content_type=content_type, text=text, table_index=table_index,
                cells=cells, operations=operations,
            )
            if result.get("ok"):
                result["_via"] = "COM fallback (file open in Word — OneDrive will sync automatically)"
            return result
        except Exception as ex:
            return {"error": f"OneDrive update failed: {ex}"}
    try:
        if action == "batch":
            if not operations:
                return {"error": "operations array is required for batch action"}
            results = []
            for i, op in enumerate(operations):
                if not isinstance(op, dict):
                    results.append({"op": i + 1, "error": f"Operation must be an object, got {type(op).__name__}"})
                    continue
                r = _tool_update_docx(
                    file_path=file_path,
                    action=op.get("action", ""),
                    find_text=op.get("find_text", ""),
                    replace_text=op.get("replace_text", ""),
                    content_type=op.get("content_type", "paragraph"),
                    text=op.get("text", ""),
                    table_index=op.get("table_index", 0),
                    cells=op.get("cells"),
                )
                results.append({"op": i + 1, **r})
                if r.get("error"):
                    break
            succeeded = sum(1 for r in results if r.get("ok"))
            return {"ok": True, "message": f"Batch: {succeeded}/{len(operations)} operations completed", "results": results}

        if file_path.startswith("open"):
            from skills._office_com import get_word_app, get_word_document, save_com_document, get_file_info
            word, err = get_word_app()
            if err:
                return {"error": err}
            doc, err = get_word_document(word, file_path)
            if err:
                return {"error": err}
            finfo = get_file_info(doc, "word")

            if action == "find_replace":
                if not find_text:
                    return {"error": "find_text is required for find_replace action"}
                find_obj = doc.Content.Find
                find_obj.ClearFormatting()
                find_obj.Replacement.ClearFormatting()
                replaced = find_obj.Execute(
                    FindText=find_text, ReplaceWith=replace_text,
                    Replace=2, Forward=True, Wrap=1,
                )
                if not replaced:
                    return {"error": f"Could not find '{find_text}' in {finfo['file_name']}. No changes were made.", **finfo}
                ok, save_err = save_com_document(doc, "word")
                if not ok:
                    return {"error": save_err, **finfo}
                return {"ok": True, **finfo, "message": f"Find/replace completed in {finfo['file_name']}", "replaced": replaced}

            elif action == "append":
                if not text:
                    return {"error": "text is required for append action"}
                rng = doc.Content
                rng.Collapse(0)
                rng.InsertParagraphAfter()
                rng.Collapse(0)
                rng.InsertAfter(text)
                last_para = doc.Paragraphs(doc.Paragraphs.Count)
                style_map = {"heading1": "Heading 1", "heading2": "Heading 2", "heading3": "Heading 3", "bullet": "List Bullet", "paragraph": "Normal"}
                last_para.Style = style_map.get(content_type, "Normal")
                ok, save_err = save_com_document(doc, "word")
                if not ok:
                    return {"error": save_err, **finfo}
                return {"ok": True, **finfo, "message": f"Appended {content_type} to {finfo['file_name']}"}

            elif action == "insert_after":
                if not find_text:
                    return {"error": "find_text is required for insert_after action"}
                if not text:
                    return {"error": "text is required for insert_after action"}
                for i in range(1, doc.Paragraphs.Count + 1):
                    para = doc.Paragraphs(i)
                    if find_text in para.Range.Text:
                        rng = para.Range
                        rng.Collapse(0)
                        rng.InsertParagraphAfter()
                        rng.Collapse(0)
                        rng.InsertAfter(text)
                        new_para = doc.Paragraphs(i + 1)
                        style_map = {"heading1": "Heading 1", "heading2": "Heading 2", "heading3": "Heading 3", "bullet": "List Bullet", "paragraph": "Normal"}
                        new_para.Style = style_map.get(content_type, "Normal")
                        ok, save_err = save_com_document(doc, "word")
                        if not ok:
                            return {"error": save_err, **finfo}
                        return {"ok": True, **finfo, "message": f"Inserted {content_type} after '{find_text}' in {finfo['file_name']}"}
                return {"error": f"Could not find paragraph containing '{find_text}'"}

            elif action == "table_update":
                if not cells:
                    return {"error": "cells array is required for table_update action"}
                tbl_count = doc.Tables.Count
                if table_index < 0 or table_index >= tbl_count:
                    return {"error": f"table_index {table_index} out of range (document has {tbl_count} table(s))"}
                tbl = doc.Tables(table_index + 1)  # COM is 1-based
                updated = 0
                errors = []
                for c in cells:
                    if not isinstance(c, dict):
                        continue
                    r, col, val = c.get("row", 0), c.get("col", 0), c.get("text", "")
                    try:
                        cell = tbl.Cell(r + 1, col + 1)  # COM is 1-based
                        cell.Range.Text = val
                        updated += 1
                    except Exception as ce:
                        errors.append(f"cell({r},{col}): {ce}")
                ok, save_err = save_com_document(doc, "word")
                if not ok:
                    return {"error": save_err, **finfo}
                msg = f"Updated {updated} cell(s) in table {table_index} of {finfo['file_name']}"
                if errors:
                    msg += f" ({len(errors)} error(s): {'; '.join(errors[:3])})"
                return {"ok": True, **finfo, "message": msg, "updated": updated}

            else:
                return {"error": f"Unknown action: {action}"}

        else:
            from docx import Document
            from docx.oxml.ns import qn
            from docx.oxml import OxmlElement
            doc = Document(file_path)

            if action == "find_replace":
                if not find_text:
                    return {"error": "find_text is required for find_replace action"}
                count = 0
                for para in doc.paragraphs:
                    if _replace_in_paragraph(para, find_text, replace_text):
                        count += 1
                for table in doc.tables:
                    for row in table.rows:
                        for cell in row.cells:
                            for para in cell.paragraphs:
                                if _replace_in_paragraph(para, find_text, replace_text):
                                    count += 1
                doc.save(file_path)
                return {"ok": True, "message": f"Replaced {count} occurrence(s) in {file_path}", "replacements": count}

            elif action == "append":
                if not text:
                    return {"error": "text is required for append action"}
                if content_type.startswith("heading"):
                    level = int(content_type[-1])
                    doc.add_heading(text, level=level)
                elif content_type == "bullet":
                    doc.add_paragraph(text, style="List Bullet")
                else:
                    doc.add_paragraph(text)
                doc.save(file_path)
                return {"ok": True, "message": f"Appended {content_type} to {file_path}"}

            elif action == "insert_after":
                if not find_text:
                    return {"error": "find_text is required for insert_after action"}
                if not text:
                    return {"error": "text is required for insert_after action"}
                for para in doc.paragraphs:
                    if find_text in para.text:
                        new_p = OxmlElement("w:p")
                        if content_type.startswith("heading"):
                            pPr = OxmlElement("w:pPr")
                            pStyle = OxmlElement("w:pStyle")
                            pStyle.set(qn("w:val"), f"Heading{content_type[-1]}")
                            pPr.append(pStyle)
                            new_p.append(pPr)
                        elif content_type == "bullet":
                            pPr = OxmlElement("w:pPr")
                            pStyle = OxmlElement("w:pStyle")
                            pStyle.set(qn("w:val"), "ListBullet")
                            pPr.append(pStyle)
                            new_p.append(pPr)
                        r = OxmlElement("w:r")
                        t = OxmlElement("w:t")
                        t.text = text
                        r.append(t)
                        new_p.append(r)
                        para._element.addnext(new_p)
                        doc.save(file_path)
                        return {"ok": True, "message": f"Inserted {content_type} after '{find_text}' in {file_path}"}
                return {"error": f"Could not find paragraph containing '{find_text}'"}

            elif action == "table_update":
                if not cells:
                    return {"error": "cells array is required for table_update action"}
                tables = doc.tables
                if table_index < 0 or table_index >= len(tables):
                    return {"error": f"table_index {table_index} out of range (document has {len(tables)} table(s))"}
                tbl = tables[table_index]
                updated = 0
                errors = []
                for c in cells:
                    if not isinstance(c, dict):
                        continue
                    r, col, val = c.get("row", 0), c.get("col", 0), c.get("text", "")
                    try:
                        col_els = _get_row_col_elements(tbl._tbl.findall(qn('w:tr'))[r], qn)
                        if col < len(col_els):
                            kind, el = col_els[col]
                            # Wrap raw tc element to get a python-docx Cell object
                            from docx.table import _Cell
                            cell_obj = _Cell(el if kind == 'tc' else el.find('.//' + qn('w:tc')), tbl)
                            _safe_write_cell(cell_obj, val)
                        else:
                            tbl.cell(r, col).text = val
                        updated += 1
                    except Exception as ce:
                        errors.append(f"cell({r},{col}): {ce}")
                doc.save(file_path)
                msg = f"Updated {updated} cell(s) in table {table_index} of {file_path}"
                if errors:
                    msg += f" ({len(errors)} error(s): {'; '.join(errors[:3])})"
                return {"ok": True, "message": msg, "updated": updated}

            elif action == "introspect_table":
                tables = doc.tables
                if table_index < 0 or table_index >= len(tables):
                    return {"error": f"table_index {table_index} out of range (document has {len(tables)} table(s))"}
                tbl = tables[table_index]
                rows_xml = tbl._tbl.findall(qn('w:tr'))
                structure = []
                for r_idx, tr in enumerate(rows_xml):
                    col_els = _get_row_col_elements(tr, qn)
                    for c_idx, (kind, el) in enumerate(col_els):
                        tc_el = el if kind == 'tc' else el.find('.//' + qn('w:tc'))
                        texts = [t.text or '' for t in tc_el.iter(qn('w:t'))]
                        preview = ''.join(texts)[:60].replace('\n', ' ')
                        has_sdt_cb = any(
                            sdt.find('.//' + qn('w14:checkbox')) is not None
                            for sdt in el.iter(qn('w:sdt'))
                        )
                        has_unicode_cb = any(ch in preview for ch in ('\u2610', '\u2611', '\u2612'))
                        tcPr = tc_el.find(qn('w:tcPr'))
                        gs = 1
                        vmerge = False
                        if tcPr is not None:
                            gs_el = tcPr.find(qn('w:gridSpan'))
                            if gs_el is not None:
                                gs = int(gs_el.get(qn('w:val'), 1))
                            vm = tcPr.find(qn('w:vMerge'))
                            if vm is not None:
                                vmerge = vm.get(qn('w:val')) is None  # no val = continuation
                        structure.append({
                            "row": r_idx, "col": c_idx,
                            "kind": kind,
                            "text_preview": preview,
                            "grid_span": gs,
                            "is_vmerge_continuation": vmerge,
                            "has_sdt_checkbox": has_sdt_cb,
                            "has_unicode_checkbox": has_unicode_cb,
                        })
                return {
                    "ok": True,
                    "file": file_path,
                    "table_index": table_index,
                    "row_count": len(rows_xml),
                    "col_count": max((e["col"] for e in structure), default=0) + 1,
                    "cells": structure,
                }

            elif action == "check_checkbox":
                if not cells:
                    return {"error": "cells array is required for check_checkbox action"}
                tables = doc.tables
                if table_index < 0 or table_index >= len(tables):
                    return {"error": f"table_index {table_index} out of range (document has {len(tables)} table(s))"}
                tbl = tables[table_index]
                rows_xml = tbl._tbl.findall(qn('w:tr'))
                updated = 0
                errors = []
                for c in cells:
                    if not isinstance(c, dict):
                        continue
                    r, col, check = c.get("row", 0), c.get("col", 0), c.get("checked", True)
                    try:
                        if r >= len(rows_xml):
                            errors.append(f"cell({r},{col}): row out of range")
                            continue
                        col_els = _get_row_col_elements(rows_xml[r], qn)
                        if col >= len(col_els):
                            errors.append(f"cell({r},{col}): col out of range (row has {len(col_els)} cols)")
                            continue
                        kind, el = col_els[col]
                        if kind == 'sdt':
                            _toggle_sdt_checkbox(el, check, qn)
                        else:
                            _toggle_checkbox_in_tc(el, check, qn)
                        updated += 1
                    except Exception as ce:
                        errors.append(f"cell({r},{col}): {ce}")
                doc.save(file_path)
                msg = f"Toggled {updated} checkbox(es) in table {table_index} of {file_path}"
                if errors:
                    msg += f" ({len(errors)} error(s): {'; '.join(errors[:3])})"
                return {"ok": True, "message": msg, "updated": updated}

            else:
                return {"error": f"Unknown action: {action}"}

    except Exception as e:
        return {"error": str(e)}


TOOL_HANDLERS = {
    "get_docx_info": _tool_get_docx_info,
    "read_docx":     _tool_read_docx,
    "create_docx":   _tool_create_docx,
    "update_docx":   _tool_update_docx,
}
