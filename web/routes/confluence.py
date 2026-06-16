"""Confluence route group — pages, spaces, search, create, update."""

import base64
import json
import os
import urllib.error
import urllib.parse
import urllib.request

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

import shared

router = APIRouter()


# ── Confluence Third-Pane Endpoints ──────────────────────────────────────────

@router.get("/api/confluence/recent-pages")
def confluence_recent_pages():
    """Return the current user's recently viewed Confluence pages."""
    try:
        from skills.confluence.api import confluence_browse_url
        email = os.environ.get("CONFLUENCE_EMAIL", "") or os.environ.get("ATLASSIAN_EMAIL", "")
        token = os.environ.get("CONFLUENCE_PAT", "") or os.environ.get("ATLASSIAN_PAT", "")
        wiki = confluence_browse_url()

        pages = []
        # Try the user-specific recently-viewed endpoint first
        if email and token:
            creds = base64.b64encode(f"{email}:{token}".encode()).decode()
            rv_url = f"{wiki}/rest/recentlyviewed/1.0/recent?limit=20"
            req = urllib.request.Request(rv_url, method="GET", headers={
                "Authorization": f"Basic {creds}",
                "Accept": "application/json",
            })
            try:
                with urllib.request.urlopen(req, timeout=15) as resp:
                    rv_data = json.loads(resp.read())
                if isinstance(rv_data, list) and rv_data:
                    for r in rv_data:
                        pages.append({
                            "id": str(r.get("id", r.get("contentId", ""))),
                            "title": r.get("title", ""),
                            "space": r.get("spaceName", r.get("space", "")),
                            "space_key": r.get("spaceKey", ""),
                            "url": f"{wiki}{r.get('url', r.get('_links', {}).get('webui', ''))}",
                            "last_modified": r.get("lastSeen", r.get("friendlyLastModified", "")),
                            "last_modifier": "",
                        })
                    return {"pages": pages}
            except Exception:
                pass  # Fall back to CQL search below

        # Fallback: globally recently modified pages (if recently-viewed endpoint unavailable)
        from skills.confluence.api import confluence_api
        cql = 'type = page order by lastModified desc'
        params = urllib.parse.urlencode({"cql": cql, "limit": 20, "expand": "space,version,history.lastUpdated"})
        data = confluence_api("GET", f"content/search?{params}")
        for r in data.get("results", []):
            history = r.get("history", {})
            last_updated = history.get("lastUpdated", {})
            pages.append({
                "id": r.get("id", ""),
                "title": r.get("title", ""),
                "space": r.get("space", {}).get("name", ""),
                "space_key": r.get("space", {}).get("key", ""),
                "url": f"{wiki}{r.get('_links', {}).get('webui', '')}",
                "last_modified": last_updated.get("when", "") if isinstance(last_updated, dict) else str(last_updated),
                "last_modifier": r.get("version", {}).get("by", {}).get("displayName", ""),
            })
        return {"pages": pages}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/api/confluence/spaces")
def confluence_spaces():
    """Return available Confluence spaces."""
    try:
        from skills.confluence.tools import _tool_list_confluence_spaces
        return _tool_list_confluence_spaces(limit=100)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/api/confluence/my-pages")
def confluence_my_pages():
    """Return pages the current user contributed to or from their personal space."""
    try:
        from skills.confluence.api import confluence_api, confluence_browse_url
        wiki = confluence_browse_url()

        data = {"results": []}
        # Strategy 1: contributor-based (works on both Cloud and Server)
        try:
            cql = 'contributor = currentUser() AND type = page ORDER BY lastModified DESC'
            params = urllib.parse.urlencode({"cql": cql, "limit": 20, "expand": "space,version"})
            data = confluence_api("GET", f"content/search?{params}")
        except Exception:
            pass

        # Strategy 2: personal space fallback if no results
        if not data.get("results"):
            try:
                me = confluence_api("GET", "user/current")
                username = me.get("username", "") or me.get("publicName", "")
                account_id = me.get("accountId", "")
                # Try ~accountId first (Cloud, stripped of colons/dashes), then raw, then ~username (Server)
                account_id_clean = account_id.replace(":", "").replace("-", "") if account_id else ""
                candidates = [f"~{account_id_clean}", f"~{account_id}", f"~{username}"] if account_id else [f"~{username}"]
                for key in candidates:
                    if not key or key == "~":
                        continue
                    try:
                        cql = f'space = "{key}" AND type = page ORDER BY lastModified DESC'
                        params = urllib.parse.urlencode({"cql": cql, "limit": 20, "expand": "space,version"})
                        data = confluence_api("GET", f"content/search?{params}")
                        if data.get("results"):
                            break
                    except Exception:
                        continue
            except Exception:
                pass
        pages = []
        for r in data.get("results", []):
            pages.append({
                "id": r.get("id", ""),
                "title": r.get("title", ""),
                "space": r.get("space", {}).get("name", ""),
                "space_key": r.get("space", {}).get("key", ""),
                "url": f"{wiki}{r.get('_links', {}).get('webui', '')}",
                "last_modified": r.get("version", {}).get("when", "")[:10],
                "last_modifier": r.get("version", {}).get("by", {}).get("displayName", ""),
            })
        return {"pages": pages}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/api/confluence/space/{space_key}/pages")
def confluence_space_pages(space_key: str):
    """Return top-level pages in a Confluence space."""
    try:
        from skills.confluence.api import confluence_api, confluence_browse_url
        data = confluence_api("GET", f"space/{space_key}/content/page?depth=root&limit=30&expand=version,children.page")
        wiki = confluence_browse_url()
        pages = []
        for r in data.get("page", {}).get("results", data.get("results", [])):
            children = r.get("children", {}).get("page", {})
            has_children = children.get("size", 0) > 0 if isinstance(children, dict) else False
            pages.append({
                "id": r.get("id", ""),
                "title": r.get("title", ""),
                "url": f"{wiki}{r.get('_links', {}).get('webui', '')}",
                "has_children": has_children,
            })
        return {"pages": pages}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/api/confluence/page/{page_id}")
def confluence_page_detail(page_id: str):
    """Return full Confluence page detail including HTML body for the third pane."""
    try:
        from skills.confluence.api import confluence_api, confluence_browse_url
        data = confluence_api("GET", f"content/{page_id}?expand=body.storage,body.view,space,version,history.lastUpdated,children.page")
        wiki = confluence_browse_url()
        body_html = data.get("body", {}).get("storage", {}).get("value", "")
        # Server-rendered HTML: macros (excerpts, panels, etc.) render faithfully,
        # unlike storage format which a browser can't display. Used for preview;
        # storage stays the source of truth for editing.
        body_view = data.get("body", {}).get("view", {}).get("value", "")
        history = data.get("history", {})
        last_updated = history.get("lastUpdated", {})
        children_data = data.get("children", {}).get("page", {}).get("results", [])
        children = [{"id": c.get("id", ""), "title": c.get("title", ""),
                      "url": f"{wiki}{c.get('_links', {}).get('webui', '')}"} for c in children_data]
        return {
            "id": data.get("id", page_id),
            "title": data.get("title", ""),
            "space": data.get("space", {}).get("name", ""),
            "space_key": data.get("space", {}).get("key", ""),
            "version": data.get("version", {}).get("number", 0),
            "url": f"{wiki}{data.get('_links', {}).get('webui', '')}",
            "body_html": body_html,
            "body_view": body_view,
            "last_modified": last_updated.get("when", "") if isinstance(last_updated, dict) else str(last_updated),
            "last_modifier": data.get("version", {}).get("by", {}).get("displayName", ""),
            "children": children,
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/api/confluence/page/{page_id}/children")
def confluence_page_children(page_id: str):
    """Return child pages of a Confluence page."""
    try:
        from skills.confluence.tools import _tool_get_confluence_child_pages
        return _tool_get_confluence_child_pages(page_id, limit=30)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/api/confluence/search")
def confluence_search(body: dict):
    """Search Confluence pages/spaces by CQL for the third-pane search bar.
    scope: 'all' | 'pages' | 'spaces' | 'recent' (default: 'all')
    """
    try:
        from skills.confluence.api import confluence_api, confluence_browse_url
        query = body.get("query", "").strip()
        scope = body.get("scope", "all")  # 'all' | 'pages' | 'spaces' | 'recent'
        if not query:
            return {"pages": [], "spaces": []}
        wiki = confluence_browse_url()
        pages = []
        spaces = []

        # Search pages (unless scope is spaces-only)
        if scope in ("all", "pages", "recent"):
            cql = f'(title ~ "{query}" OR text ~ "{query}") AND type = page'
            params = urllib.parse.urlencode({"cql": cql, "limit": 15, "expand": "space,version,history.lastUpdated"})
            data = confluence_api("GET", f"content/search?{params}")
            for r in data.get("results", []):
                history = r.get("history", {})
                last_updated = history.get("lastUpdated", {})
                pages.append({
                    "id": r.get("id", ""),
                    "title": r.get("title", ""),
                    "space": r.get("space", {}).get("name", r.get("resultGlobalContainer", {}).get("title", "")),
                    "url": f"{wiki}{r.get('_links', {}).get('webui', '')}",
                    "excerpt": r.get("excerpt", "")[:200],
                    "last_modified": last_updated.get("when", "") if isinstance(last_updated, dict) else str(last_updated),
                })

        # Search spaces (for 'all' and 'spaces' scopes) — use space endpoint with client-side filter
        if scope in ("all", "spaces"):
            try:
                space_data = confluence_api("GET", "space?limit=100&type=global")
                q_lower = query.lower()
                for s in space_data.get("results", []):
                    name = s.get("name", "")
                    key = s.get("key", "")
                    if q_lower in name.lower() or q_lower in key.lower():
                        spaces.append({"key": key, "name": name, "type": s.get("type", "")})
            except Exception:
                pass

        return {"pages": pages, "spaces": spaces}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/api/confluence/page")
def confluence_create_page(body: dict):
    """Create a Confluence page from the third-pane form (human-reviewed)."""
    try:
        from skills.confluence.api import confluence_api, confluence_browse_url
        space_key = body.get("space_key", "")
        title = body.get("title", "")
        page_body = body.get("body", "")
        parent_id = body.get("parent_id", "")
        if not space_key or not title:
            raise HTTPException(status_code=400, detail="space_key and title are required")
        payload: dict = {
            "type": "page",
            "title": title,
            "space": {"key": space_key},
            "body": {"storage": {"value": page_body, "representation": "storage"}},
        }
        if parent_id:
            payload["ancestors"] = [{"id": parent_id}]
        try:
            data = confluence_api("POST", "content", payload)
        except Exception as api_err:
            err_str = str(api_err)
            if "404" in err_str and space_key.startswith("~"):
                raise HTTPException(
                    status_code=404,
                    detail=f"Personal space '{space_key}' does not exist. "
                           f"In Confluence, go to your profile and click 'Create personal space' first, "
                           f"then try again. Or choose a different space."
                )
            raise
        wiki = confluence_browse_url()
        return {
            "created": True,
            "id": data.get("id", ""),
            "title": data.get("title", title),
            "url": f"{wiki}{data.get('_links', {}).get('webui', '')}",
        }
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.put("/api/confluence/page/{page_id}")
def confluence_update_page(page_id: str, body: dict):
    """Update a Confluence page from the third-pane edit form."""
    try:
        from skills.confluence.api import confluence_api, confluence_browse_url
        title = body.get("title", "")
        page_body = body.get("body", "")
        version = body.get("version", 0)
        if not page_body:
            raise HTTPException(status_code=400, detail="body is required")
        if not version:
            current = confluence_api("GET", f"content/{page_id}?expand=version")
            version = current.get("version", {}).get("number", 1)
            if not title:
                title = current.get("title", "")
        # Validate well-formedness BEFORE the PUT so the human gets a clear,
        # actionable message instead of an opaque Confluence parse 400.
        from skills.confluence.tools import _structural_errors, _find_unbalanced_anchor
        err = _structural_errors(page_body)
        if err:
            parts = ["This page can't be saved — the content isn't balanced, so Confluence would reject it."]
            anchor = _find_unbalanced_anchor(page_body)
            if anchor and anchor.get("reason"):
                parts.append(anchor["reason"])
                if anchor.get("text"):
                    parts.append(f"Near: “{anchor['text']}”")
            elif err.get("message"):
                parts.append(err["message"])
            raise HTTPException(status_code=400, detail=" ".join(parts))
        payload = {
            "type": "page",
            "title": title,
            "version": {"number": version + 1},
            "body": {"storage": {"value": page_body, "representation": "storage"}},
        }
        data = confluence_api("PUT", f"content/{page_id}", payload)
        wiki = confluence_browse_url()
        return {
            "updated": True,
            "id": data.get("id", page_id),
            "title": data.get("title", title),
            "version": data.get("version", {}).get("number", version + 1),
            "url": f"{wiki}{data.get('_links', {}).get('webui', '')}",
        }
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
