"""OneNote skill -- 7 tools."""
import json
import re
import urllib.request as _ur
import urllib.error as _ue
from pathlib import Path

ONENOTE_SKILLS_DIR = Path(__file__).parent.parent / "m365-onenote" / "scripts"

SKILL_ID = "onenote"
SKILL_ALIASES = ["onenote"]
ALWAYS_ON = False

TOOL_DEFS = [
    {
        "name": "list_onenote_notebooks",
        "description": "List the user's OneNote notebooks. Call this first when the user asks about OneNote or wants to find a notebook/section.",
        "input_schema": {"type": "object", "properties": {}, "required": []},
    },
    {
        "name": "list_onenote_sections",
        "description": "List sections in a OneNote notebook. Call after list_onenote_notebooks to get section IDs.",
        "input_schema": {
            "type": "object",
            "properties": {
                "notebook_id": {"type": "string", "description": "Notebook ID from list_onenote_notebooks"},
            },
            "required": ["notebook_id"],
        },
    },
    {
        "name": "list_onenote_pages",
        "description": "List pages in a OneNote section.",
        "input_schema": {
            "type": "object",
            "properties": {
                "section_id": {"type": "string", "description": "Section ID from list_onenote_sections"},
                "count": {"type": "integer", "description": "Max pages. Default 100.", "default": 100},
            },
            "required": ["section_id"],
        },
    },
    {
        "name": "create_onenote_page",
        "description": "Create a new page in a OneNote section. Always call list_onenote_notebooks then list_onenote_sections first to get the section_id.",
        "input_schema": {
            "type": "object",
            "properties": {
                "section_id": {"type": "string", "description": "Section ID to create the page in"},
                "title": {"type": "string", "description": "Page title"},
                "body": {"type": "string", "description": "Page content (plain text or HTML)"},
                "html": {"type": "boolean", "description": "If true, body is treated as HTML", "default": False},
            },
            "required": ["section_id", "title", "body"],
        },
    },
    {
        "name": "read_onenote_page",
        "description": "Read the content of a OneNote page. Returns the page title and body as plain text. Use to read, summarize, or answer questions about a page's content.",
        "input_schema": {
            "type": "object",
            "properties": {
                "page_id": {"type": "string", "description": "Page ID from list_onenote_pages or a pinned page"},
            },
            "required": ["page_id"],
        },
    },
    {
        "name": "update_onenote_page",
        "description": "Append content to an existing OneNote page. Use this to add items, update status, or extend a page without overwriting it. Requires page_id \u2014 get it from list_onenote_pages or a pinned page.",
        "input_schema": {
            "type": "object",
            "properties": {
                "page_id": {"type": "string", "description": "Page ID from list_onenote_pages or a pinned page"},
                "content": {"type": "string", "description": "Content to append (plain text or HTML)"},
                "html": {"type": "boolean", "description": "If true, content is treated as HTML", "default": False},
            },
            "required": ["page_id", "content"],
        },
    },
    {
        "name": "pin_onenote_page",
        "description": "Pin a OneNote page so the user can reference it by name without re-navigating. Say 'pin this page' after finding it. Pinned pages persist for the session.",
        "input_schema": {
            "type": "object",
            "properties": {
                "page_id": {"type": "string", "description": "Page ID to pin"},
                "page_title": {"type": "string", "description": "Page title for display"},
                "notebook_name": {"type": "string", "description": "Notebook name for context"},
                "section_name": {"type": "string", "description": "Section name for context"},
            },
            "required": ["page_id", "page_title"],
        },
    },
]

TOOL_STATUS = {
    "list_onenote_notebooks": "\U0001f4d3 Loading notebooks...",
    "list_onenote_sections": "\U0001f4d3 Loading sections...",
    "list_onenote_pages": "\U0001f4d3 Loading pages...",
    "create_onenote_page": "\U0001f4d3 Creating page...",
    "read_onenote_page": "\U0001f4d3 Reading page...",
    "update_onenote_page": "\U0001f4d3 Updating page...",
    "pin_onenote_page": "\U0001f4cc Pinning page...",
}


def _paginate_onenote(gc, path: str, params: dict, max_items: int = 500) -> list:
    """Fetch all pages of a Graph OneNote list endpoint, following @odata.nextLink."""
    import urllib.parse as _up
    _ALLOWED = ("graph.microsoft.com",)

    def _safe_next(url: str) -> str:
        host = _up.urlparse(url).netloc.lower().split(":")[0]
        if not any(host == h or host.endswith("." + h) for h in _ALLOWED):
            raise ValueError(f"Refusing nextLink to untrusted host: {host}")
        return url

    items = []
    data = gc.get(path, params=params)
    items.extend(data.get("value", []))
    while "@odata.nextLink" in data and len(items) < max_items:
        data = gc.get_absolute(_safe_next(data["@odata.nextLink"]))
        items.extend(data.get("value", []))
    return items[:max_items]


def _tool_list_onenote_notebooks() -> dict:
    from .._m365.helpers import get_skill_client
    gc = get_skill_client(ONENOTE_SKILLS_DIR)
    items = _paginate_onenote(gc, "/me/onenote/notebooks",
                              {"$orderby": "displayName",
                               "$select": "id,displayName,lastModifiedDateTime,links"})
    return {"notebooks": [{"name": n.get("displayName", ""), "id": n.get("id", ""),
                           "modified": (n.get("lastModifiedDateTime") or "")[:16],
                           "url": (n.get("links") or {}).get("oneNoteWebUrl", {}).get("href", "")}
                          for n in items]}


def _tool_list_onenote_sections(notebook_id: str) -> dict:
    from .._m365.helpers import get_skill_client
    gc = get_skill_client(ONENOTE_SKILLS_DIR)
    items = _paginate_onenote(gc, f"/me/onenote/notebooks/{notebook_id}/sections",
                              {"$select": "id,displayName,createdDateTime"})
    return {"sections": [{"name": s.get("displayName", ""), "id": s.get("id", ""),
                          "created": (s.get("createdDateTime") or "")[:16]}
                         for s in items]}


def _tool_list_onenote_pages(section_id: str, count: int = 100) -> dict:
    from .._m365.helpers import get_skill_client
    gc = get_skill_client(ONENOTE_SKILLS_DIR)
    items = _paginate_onenote(gc, f"/me/onenote/sections/{section_id}/pages",
                              {"$top": str(min(count, 100)),
                               "$orderby": "lastModifiedDateTime desc",
                               "$select": "id,title,lastModifiedDateTime,links"},
                              max_items=count)
    return {"pages": [{"title": p.get("title") or "(untitled)", "id": p.get("id", ""),
                       "modified": (p.get("lastModifiedDateTime") or "")[:16],
                       "url": (p.get("links") or {}).get("oneNoteWebUrl", {}).get("href", "")}
                      for p in items]}


def _tool_create_onenote_page(section_id: str, title: str, body: str, html: bool = False) -> dict:
    from .._m365.helpers import get_skill_client
    import html as _html_mod
    gc = get_skill_client(ONENOTE_SKILLS_DIR)
    if not html:
        body = body.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace("\n", "<br/>")
    safe_title = _html_mod.escape(title)
    page_html = f"<!DOCTYPE html><html><head><title>{safe_title}</title></head><body>{body}</body></html>"
    # Route through GraphClient._request so Retry-After/429 retry logic applies
    url = f"https://graph.microsoft.com/v1.0/me/onenote/sections/{section_id}/pages"
    resp = gc._request("POST", url,
                       headers={**gc._headers(), "Content-Type": "application/xhtml+xml"},
                       content=page_html.encode("utf-8"),
                       label=f"onenote/sections/{section_id}/pages")
    result = resp.json()
    return {"created": True, "title": result.get("title", title), "id": result.get("id", ""),
            "url": (result.get("links") or {}).get("oneNoteWebUrl", {}).get("href", "")}


def _tool_read_onenote_page(page_id: str) -> dict:
    """Read a OneNote page's content as plain text."""
    from .._m365.helpers import get_skill_client
    gc = get_skill_client(ONENOTE_SKILLS_DIR)
    token = gc.get_token()

    # Get metadata
    meta = gc.get(f"/me/onenote/pages/{page_id}",
                  params={"$select": "id,title,lastModifiedDateTime"})

    # Get HTML content
    url = f"https://graph.microsoft.com/v1.0/me/onenote/pages/{page_id}/content"
    req = _ur.Request(url, headers={"Authorization": f"Bearer {token}", "Accept": "text/html"}, method="GET")
    try:
        with _ur.urlopen(req, timeout=30) as resp:
            html_content = resp.read().decode("utf-8", errors="replace")
    except _ue.HTTPError as e:
        raise RuntimeError(f"Graph API {e.code}: {e.read().decode()[:300]}")

    # Convert HTML to plain text
    text = re.sub(r'<br\s*/?>', '\n', html_content)
    text = re.sub(r'</(p|div|h[1-6]|li|tr)>', '\n', text)
    text = re.sub(r'<[^>]+>', '', text)
    text = text.replace('&amp;', '&').replace('&lt;', '<').replace('&gt;', '>').replace('&nbsp;', ' ')
    text = re.sub(r'\n{3,}', '\n\n', text).strip()

    return {
        "title": meta.get("title", "(untitled)"),
        "id": page_id,
        "modified": meta.get("lastModifiedDateTime", "")[:16],
        "content": text[:5000],  # cap to avoid huge payloads
    }


def _tool_update_onenote_page(page_id: str, content: str, html: bool = False) -> dict:
    """Append content to an existing OneNote page."""
    from .._m365.helpers import get_skill_client
    gc = get_skill_client(ONENOTE_SKILLS_DIR)
    if not html:
        content = content.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace("\n", "<br/>")
    patch_ops = [{"target": "body", "action": "append", "content": f"<div>{content}</div>"}]
    url = f"https://graph.microsoft.com/v1.0/me/onenote/pages/{page_id}/content"
    data = json.dumps(patch_ops).encode()
    req = _ur.Request(url, data=data, headers={
        "Authorization": f"Bearer {gc.get_token()}",
        "Content-Type": "application/json",
    }, method="PATCH")
    try:
        with _ur.urlopen(req, timeout=30) as resp:
            pass  # 204 No Content
    except _ue.HTTPError as e:
        raise RuntimeError(f"Graph API {e.code}: {e.read().decode()[:300]}")
    return {"updated": True, "page_id": page_id}


def _tool_pin_onenote_page(page_id: str, page_title: str, notebook_name: str = "", section_name: str = "") -> dict:
    """Pin a OneNote page for quick reference."""
    from .state import pinned_onenote_pages
    pinned_onenote_pages[page_title.lower()] = {
        "page_id": page_id,
        "title": page_title,
        "notebook": notebook_name,
        "section": section_name,
    }
    return {"pinned": True, "title": page_title, "page_id": page_id,
            "hint": f"You can now reference this page by name. Currently pinned: {', '.join(p['title'] for p in pinned_onenote_pages.values())}"}


TOOL_HANDLERS = {
    "list_onenote_notebooks": _tool_list_onenote_notebooks,
    "list_onenote_sections": _tool_list_onenote_sections,
    "list_onenote_pages": _tool_list_onenote_pages,
    "create_onenote_page": _tool_create_onenote_page,
    "read_onenote_page": _tool_read_onenote_page,
    "update_onenote_page": _tool_update_onenote_page,
    "pin_onenote_page": _tool_pin_onenote_page,
}
