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
        "description": "List the user's PERSONAL OneNote notebooks (fast). Call this first for general OneNote browsing. NOTE: this does NOT include SharePoint team/shared notebooks — to find a specific team notebook by name (e.g. from a pin), use find_onenote_notebook(name) instead. Each returned notebook has a 'site_id' field ('' for personal) to pass to downstream tools.",
        "input_schema": {"type": "object", "properties": {}, "required": []},
    },
    {
        "name": "find_onenote_notebook",
        "description": "Find a OneNote notebook by name across BOTH personal and SharePoint team notebooks. FASTER than list_onenote_notebooks when you know the name (e.g. resolving a pinned notebook) — it searches SharePoint sites by name instead of sweeping all sites. Returns matching notebooks each with a 'site_id' (empty for personal, non-empty for team). Use this first when a pin references a specific notebook name.",
        "input_schema": {
            "type": "object",
            "properties": {
                "name": {
                    "type": "string",
                    "description": "Notebook name (or partial) to find, e.g. 'LLM Gateway Notebook'",
                },
            },
            "required": ["name"],
        },
    },
    {
        "name": "list_onenote_sections",
        "description": "List sections in a OneNote notebook. Call after list_onenote_notebooks to get section IDs. For SharePoint team notebooks, pass the notebook's site_id.",
        "input_schema": {
            "type": "object",
            "properties": {
                "notebook_id": {
                    "type": "string",
                    "description": "Notebook ID from list_onenote_notebooks",
                },
                "site_id": {
                    "type": "string",
                    "description": "SharePoint site id (from the notebook's site_id field). Omit or '' for personal notebooks.",
                    "default": "",
                },
            },
            "required": ["notebook_id"],
        },
    },
    {
        "name": "list_onenote_pages",
        "description": "List pages in a OneNote section. For SharePoint team notebooks, pass the site_id.",
        "input_schema": {
            "type": "object",
            "properties": {
                "section_id": {
                    "type": "string",
                    "description": "Section ID from list_onenote_sections",
                },
                "count": {
                    "type": "integer",
                    "description": "Max pages. Default 100.",
                    "default": 100,
                },
                "site_id": {
                    "type": "string",
                    "description": "SharePoint site id (same site_id the section came from). Omit or '' for personal notebooks.",
                    "default": "",
                },
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
                "section_id": {
                    "type": "string",
                    "description": "Section ID to create the page in",
                },
                "title": {"type": "string", "description": "Page title"},
                "body": {
                    "type": "string",
                    "description": "Page content (plain text or HTML)",
                },
                "html": {
                    "type": "boolean",
                    "description": "If true, body is treated as HTML",
                    "default": False,
                },
            },
            "required": ["section_id", "title", "body"],
        },
    },
    {
        "name": "read_onenote_page",
        "description": "Read the content of a OneNote page. Returns the page title and body as plain text. Use to read, summarize, or answer questions about a page's content. For pages in SharePoint team notebooks, pass the site_id.",
        "input_schema": {
            "type": "object",
            "properties": {
                "page_id": {
                    "type": "string",
                    "description": "Page ID from list_onenote_pages or a pinned page",
                },
                "site_id": {
                    "type": "string",
                    "description": "SharePoint site id (same site_id the page came from). Omit or '' for personal notebooks.",
                    "default": "",
                },
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
                "page_id": {
                    "type": "string",
                    "description": "Page ID from list_onenote_pages or a pinned page",
                },
                "content": {
                    "type": "string",
                    "description": "Content to append (plain text or HTML)",
                },
                "html": {
                    "type": "boolean",
                    "description": "If true, content is treated as HTML",
                    "default": False,
                },
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
                "page_title": {
                    "type": "string",
                    "description": "Page title for display",
                },
                "notebook_name": {
                    "type": "string",
                    "description": "Notebook name for context",
                },
                "section_name": {
                    "type": "string",
                    "description": "Section name for context",
                },
            },
            "required": ["page_id", "page_title"],
        },
    },
]

TOOL_STATUS = {
    "list_onenote_notebooks": "\U0001f4d3 Loading notebooks...",
    "find_onenote_notebook": "\U0001f4d3 Finding notebook...",
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


# OneNote lives in TWO Graph roots:
#   /me/onenote/...           → the user's PERSONAL notebooks (MySite/OneDrive)
#   /sites/{site-id}/onenote/ → SharePoint TEAM/SHARED site notebooks
# The token carries both Notes.ReadWrite.All and Sites.ReadWrite.All, so both
# work. Section/page/read tools take an optional site_id to pick the right root.
def _onenote_root(site_id: str = "") -> str:
    return f"/sites/{site_id}/onenote" if site_id else "/me/onenote"


def _tool_list_onenote_notebooks(include_sites: bool = False) -> dict:
    """List OneNote notebooks. Returns PERSONAL notebooks by default (fast).
    Set include_sites=True to ALSO sweep all SharePoint site notebooks — but that
    is slow (probes up to 50 sites). To find a SPECIFIC team notebook by name,
    prefer find_onenote_notebook(name) which is fast and targeted.
    Each notebook carries a site_id ('' for personal) that MUST be passed to
    list_onenote_sections/list_onenote_pages/read_onenote_page for site notebooks."""
    from .._m365.helpers import get_skill_client

    gc = get_skill_client(ONENOTE_SKILLS_DIR)

    def _fmt(n, site_id=""):
        return {
            "name": n.get("displayName", ""),
            "id": n.get("id", ""),
            "site_id": site_id,
            "modified": (n.get("lastModifiedDateTime") or "")[:16],
            "url": (n.get("links") or {}).get("oneNoteWebUrl", {}).get("href", ""),
        }

    # 1. Personal notebooks
    personal = _paginate_onenote(
        gc,
        "/me/onenote/notebooks",
        {
            "$orderby": "displayName",
            "$select": "id,displayName,lastModifiedDateTime,links",
        },
    )
    notebooks = [_fmt(n) for n in personal]

    # 2. SharePoint site notebooks — sweep the sites the user can see and merge.
    #    Reuses the same /sites?search= pattern OneDrive uses to reach site content.
    #    Parallelized: querying 50 sites sequentially (~1.5s each) would take >60s,
    #    so we fan out with a thread pool. Most sites have 0 notebooks (fast 404/empty).
    if include_sites:
        seen_ids = {nb["id"] for nb in notebooks}
        try:
            sites_data = gc.get(
                "/sites",
                params={"search": "*", "$select": "id,displayName", "$top": "50"},
            )
            sites = [s for s in (sites_data.get("value") or []) if s.get("id")][:50]

            def _site_notebooks(site):
                sid = site.get("id", "")
                try:
                    nbs = _paginate_onenote(
                        gc,
                        f"/sites/{sid}/onenote/notebooks",
                        {"$select": "id,displayName,lastModifiedDateTime,links"},
                        max_items=50,
                    )
                    return (site, nbs)
                except Exception:
                    return (site, [])

            from concurrent.futures import ThreadPoolExecutor

            with ThreadPoolExecutor(max_workers=10) as ex:
                for site, site_nbs in ex.map(_site_notebooks, sites):
                    for n in site_nbs:
                        if n.get("id") in seen_ids:
                            continue
                        seen_ids.add(n.get("id"))
                        nb = _fmt(n, site.get("id", ""))
                        nb["site_name"] = site.get("displayName", "")
                        notebooks.append(nb)
        except Exception:
            pass  # sites search unavailable — personal notebooks still returned

    return {"notebooks": notebooks}


def _tool_find_onenote_notebook(name: str) -> dict:
    """Find a OneNote notebook by name across personal AND SharePoint site
    notebooks. Faster/targeted alternative to list_onenote_notebooks when you
    know the notebook name (e.g. from a pin). Searches sites by the name so it
    only probes a handful of matching sites, not all 50."""
    from .._m365.helpers import get_skill_client

    gc = get_skill_client(ONENOTE_SKILLS_DIR)
    matches = []

    def _fmt(n, site_id="", site_name=""):
        return {
            "name": n.get("displayName", ""),
            "id": n.get("id", ""),
            "site_id": site_id,
            "site_name": site_name,
            "url": (n.get("links") or {}).get("oneNoteWebUrl", {}).get("href", ""),
        }

    # 1. Personal notebooks
    try:
        personal = _paginate_onenote(
            gc, "/me/onenote/notebooks", {"$select": "id,displayName,links"}
        )
        for n in personal:
            if name.lower() in (n.get("displayName", "") or "").lower():
                matches.append(_fmt(n))
    except Exception:
        pass

    # 2. Site notebooks — search sites by name (targeted). The SharePoint SITE
    #    name often differs from the NOTEBOOK name (e.g. site "LLM Gateway" holds
    #    notebook "LLM Gateway Notebook"). So try progressively looser search
    #    terms: full name, name minus trailing "Notebook", then the first 1-2 words.
    #    Collect candidate sites across all queries, dedupe, then probe each once.
    _terms = []
    _n = name.strip()
    _terms.append(_n)
    _no_nb = re.sub(r"\s*notebook\s*$", "", _n, flags=re.I).strip()
    if _no_nb and _no_nb != _n:
        _terms.append(_no_nb)
    _words = _no_nb.split()
    if len(_words) > 2:
        _terms.append(" ".join(_words[:2]))
    if len(_words) > 1:
        _terms.append(_words[0])

    candidate_sites = {}  # site_id -> displayName
    for term in _terms:
        if not term:
            continue
        try:
            sites_data = gc.get(
                "/sites",
                params={"search": term, "$select": "id,displayName", "$top": "20"},
            )
            for site in (sites_data.get("value") or [])[:20]:
                sid = site.get("id", "")
                if sid:
                    candidate_sites[sid] = site.get("displayName", "")
        except Exception:
            continue
        # Stop early once we have some candidates from a broad-enough term
        if candidate_sites and term == _no_nb:
            break

    # Probe each candidate site's notebooks (parallel), match by notebook name.
    def _probe(item):
        sid, sname = item
        try:
            nbs = _paginate_onenote(
                gc,
                f"/sites/{sid}/onenote/notebooks",
                {"$select": "id,displayName,links"},
                max_items=50,
            )
            return (sid, sname, nbs)
        except Exception:
            return (sid, sname, [])

    try:
        from concurrent.futures import ThreadPoolExecutor

        with ThreadPoolExecutor(max_workers=10) as ex:
            for sid, sname, nbs in ex.map(_probe, list(candidate_sites.items())):
                for n in nbs:
                    dn = (n.get("displayName", "") or "").lower()
                    # Match if the notebook name contains the query OR vice-versa
                    if name.lower() in dn or dn in name.lower() or _no_nb.lower() in dn:
                        matches.append(_fmt(n, sid, sname))
    except Exception:
        pass

    # Dedupe by notebook id
    _seen = set()
    _uniq = []
    for m in matches:
        if m["id"] in _seen:
            continue
        _seen.add(m["id"])
        _uniq.append(m)

    return {"notebooks": _uniq}


def _tool_list_onenote_sections(notebook_id: str, site_id: str = "") -> dict:
    from .._m365.helpers import get_skill_client

    gc = get_skill_client(ONENOTE_SKILLS_DIR)
    items = _paginate_onenote(
        gc,
        f"{_onenote_root(site_id)}/notebooks/{notebook_id}/sections",
        {"$select": "id,displayName,createdDateTime"},
    )
    return {
        "sections": [
            {
                "name": s.get("displayName", ""),
                "id": s.get("id", ""),
                "site_id": site_id,
                "created": (s.get("createdDateTime") or "")[:16],
            }
            for s in items
        ]
    }


def _tool_list_onenote_pages(
    section_id: str, count: int = 100, site_id: str = ""
) -> dict:
    from .._m365.helpers import get_skill_client

    gc = get_skill_client(ONENOTE_SKILLS_DIR)
    items = _paginate_onenote(
        gc,
        f"{_onenote_root(site_id)}/sections/{section_id}/pages",
        {
            "$top": str(min(count, 100)),
            "$orderby": "lastModifiedDateTime desc",
            "$select": "id,title,lastModifiedDateTime,links",
        },
        max_items=count,
    )
    return {
        "pages": [
            {
                "title": p.get("title") or "(untitled)",
                "id": p.get("id", ""),
                "site_id": site_id,
                "modified": (p.get("lastModifiedDateTime") or "")[:16],
                "url": (p.get("links") or {}).get("oneNoteWebUrl", {}).get("href", ""),
            }
            for p in items
        ]
    }


def _tool_create_onenote_page(
    section_id: str, title: str, body: str, html: bool = False
) -> dict:
    from .._m365.helpers import get_skill_client
    import html as _html_mod

    gc = get_skill_client(ONENOTE_SKILLS_DIR)
    if not html:
        body = (
            body.replace("&", "&amp;")
            .replace("<", "&lt;")
            .replace(">", "&gt;")
            .replace("\n", "<br/>")
        )
    safe_title = _html_mod.escape(title)
    page_html = f"<!DOCTYPE html><html><head><title>{safe_title}</title></head><body>{body}</body></html>"
    # Route through GraphClient._request so Retry-After/429 retry logic applies
    url = f"https://graph.microsoft.com/v1.0/me/onenote/sections/{section_id}/pages"
    resp = gc._request(
        "POST",
        url,
        headers={**gc._headers(), "Content-Type": "application/xhtml+xml"},
        content=page_html.encode("utf-8"),
        label=f"onenote/sections/{section_id}/pages",
    )
    result = resp.json()
    return {
        "created": True,
        "title": result.get("title", title),
        "id": result.get("id", ""),
        "url": (result.get("links") or {}).get("oneNoteWebUrl", {}).get("href", ""),
    }


def _tool_read_onenote_page(page_id: str, site_id: str = "") -> dict:
    """Read a OneNote page's content as plain text. Pass site_id for pages in
    SharePoint team/shared notebooks (from list_onenote_pages)."""
    from .._m365.helpers import get_skill_client

    gc = get_skill_client(ONENOTE_SKILLS_DIR)
    token = gc.get_token()
    root = _onenote_root(site_id)

    # Get metadata
    meta = gc.get(
        f"{root}/pages/{page_id}", params={"$select": "id,title,lastModifiedDateTime"}
    )

    # Get HTML content
    url = f"https://graph.microsoft.com/v1.0{root}/pages/{page_id}/content"
    req = _ur.Request(
        url,
        headers={"Authorization": f"Bearer {token}", "Accept": "text/html"},
        method="GET",
    )
    try:
        with _ur.urlopen(req, timeout=30) as resp:
            html_content = resp.read().decode("utf-8", errors="replace")
    except _ue.HTTPError as e:
        raise RuntimeError(f"Graph API {e.code}: {e.read().decode()[:300]}")

    # Convert HTML to plain text
    text = re.sub(r"<br\s*/?>", "\n", html_content)
    text = re.sub(r"</(p|div|h[1-6]|li|tr)>", "\n", text)
    text = re.sub(r"<[^>]+>", "", text)
    text = (
        text.replace("&amp;", "&")
        .replace("&lt;", "<")
        .replace("&gt;", ">")
        .replace("&nbsp;", " ")
    )
    text = re.sub(r"\n{3,}", "\n\n", text).strip()

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
        content = (
            content.replace("&", "&amp;")
            .replace("<", "&lt;")
            .replace(">", "&gt;")
            .replace("\n", "<br/>")
        )
    patch_ops = [
        {"target": "body", "action": "append", "content": f"<div>{content}</div>"}
    ]
    url = f"https://graph.microsoft.com/v1.0/me/onenote/pages/{page_id}/content"
    data = json.dumps(patch_ops).encode()
    req = _ur.Request(
        url,
        data=data,
        headers={
            "Authorization": f"Bearer {gc.get_token()}",
            "Content-Type": "application/json",
        },
        method="PATCH",
    )
    try:
        with _ur.urlopen(req, timeout=30) as resp:
            pass  # 204 No Content
    except _ue.HTTPError as e:
        raise RuntimeError(f"Graph API {e.code}: {e.read().decode()[:300]}")
    return {"updated": True, "page_id": page_id}


def _tool_pin_onenote_page(
    page_id: str, page_title: str, notebook_name: str = "", section_name: str = ""
) -> dict:
    """Pin a OneNote page for quick reference."""
    from .state import pinned_onenote_pages

    pinned_onenote_pages[page_title.lower()] = {
        "page_id": page_id,
        "title": page_title,
        "notebook": notebook_name,
        "section": section_name,
    }
    return {
        "pinned": True,
        "title": page_title,
        "page_id": page_id,
        "hint": f"You can now reference this page by name. Currently pinned: {', '.join(p['title'] for p in pinned_onenote_pages.values())}",
    }


TOOL_HANDLERS = {
    "list_onenote_notebooks": _tool_list_onenote_notebooks,
    "find_onenote_notebook": _tool_find_onenote_notebook,
    "list_onenote_sections": _tool_list_onenote_sections,
    "list_onenote_pages": _tool_list_onenote_pages,
    "create_onenote_page": _tool_create_onenote_page,
    "read_onenote_page": _tool_read_onenote_page,
    "update_onenote_page": _tool_update_onenote_page,
    "pin_onenote_page": _tool_pin_onenote_page,
}
