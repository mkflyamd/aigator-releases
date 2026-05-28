"""Confluence skill — tools."""
import html as _html_mod
import re
import urllib.parse
from .api import confluence_api, confluence_browse_url

SKILL_ID = "confluence"
ALWAYS_ON = False


def _html_to_text(raw_html: str, max_len: int = 0) -> str:
    text = re.sub(r"<br\s*/?>", "\n", raw_html, flags=re.IGNORECASE)
    text = re.sub(r"</p>|</div>|</tr>|</li>", "\n", text, flags=re.IGNORECASE)
    text = re.sub(r"<[^>]+>", "", text)
    text = _html_mod.unescape(text)
    text = text.replace("\u00a0", " ")
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    text = text.strip()
    return text[:max_len] if max_len else text


TOOL_DEFS = [
    {
        "name": "search_confluence",
        "description": "Search Confluence wiki pages. Use when user asks about documentation, processes, how-to guides, or wants to find specific information.",
        "input_schema": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "Search keywords"},
                "limit": {"type": "integer", "description": "Max results to return (default 10, max 25)", "default": 10},
            },
            "required": ["query"],
        },
    },
    {
        "name": "read_confluence_page",
        "description": "Read the full content of a Confluence page by page ID or URL. Use when the user provides a Confluence link or you need the full body of a specific page. Extract the page ID from URLs like https://amd.atlassian.net/wiki/spaces/SPACE/pages/12345/Title — the ID is 12345.",
        "input_schema": {
            "type": "object",
            "properties": {
                "page_id": {"type": "string", "description": "Confluence page ID (numeric) or full page URL"},
            },
            "required": ["page_id"],
        },
    },
    {
        "name": "create_confluence_page",
        "description": "Create a new Confluence page. Provide space key, title, and HTML body content.",
        "input_schema": {"type": "object", "properties": {
            "space_key": {"type": "string", "description": "Space key e.g. AIG, DEV"},
            "title": {"type": "string", "description": "Page title"},
            "body": {"type": "string", "description": "Page body in Confluence storage format (HTML)"},
            "parent_id": {"type": "string", "description": "Optional parent page ID to create as child page"},
        }, "required": ["space_key", "title", "body"]},
    },
    {
        "name": "update_confluence_page",
        "description": "Update an existing Confluence page. Requires page ID and new content. Automatically handles version increment.",
        "input_schema": {"type": "object", "properties": {
            "page_id": {"type": "string", "description": "Confluence page ID (numeric)"},
            "title": {"type": "string", "description": "New title (optional — keeps current if omitted)"},
            "body": {"type": "string", "description": "New body in Confluence storage format (HTML)"},
        }, "required": ["page_id", "body"]},
    },
    {
        "name": "list_confluence_spaces",
        "description": "List available Confluence spaces. Use when user asks what spaces exist or needs to find a space key.",
        "input_schema": {"type": "object", "properties": {
            "limit": {"type": "integer", "description": "Max spaces to return, default 25", "default": 25},
        }, "required": []},
    },
    {
        "name": "get_confluence_child_pages",
        "description": "Get child pages of a Confluence page. Use to navigate page hierarchy or list sub-pages.",
        "input_schema": {"type": "object", "properties": {
            "page_id": {"type": "string", "description": "Parent page ID (numeric)"},
            "limit": {"type": "integer", "description": "Max results, default 25", "default": 25},
        }, "required": ["page_id"]},
    },
    {
        "name": "confluence_show_pages",
        "description": "Update the Confluence sidebar with a list of pages. Call this AFTER search_confluence to stream results into the sidebar pane.",
        "input_schema": {"type": "object", "properties": {
            "pages": {"type": "string", "description": "JSON string of pages array from search_confluence results"},
            "title": {"type": "string", "description": "Header label for the list, e.g. 'Search results'"},
        }, "required": ["pages"]},
    },
    {
        "name": "confluence_open_create_form",
        "description": "Open the page creation form in the Confluence sidebar. Pre-fill space key, title, and body. The user reviews and clicks Create.",
        "input_schema": {"type": "object", "properties": {
            "space_key": {"type": "string", "description": "Space key e.g. DEV, AIG"},
            "title": {"type": "string", "description": "Pre-filled page title"},
            "body": {"type": "string", "description": "Pre-filled body in HTML"},
            "parent_id": {"type": "string", "description": "Optional parent page ID to create as child page"},
        }, "required": ["space_key"]},
    },
    {
        "name": "patch_confluence_page",
        "description": "Surgically edit a Confluence page. Reads the current body, finds the anchor, and applies the change. Use this instead of update_confluence_page for targeted edits. Matching strategy (tried in order): 1) exact HTML, 2) whitespace-normalized, 3) plain-text (tags stripped), 4) macro name (e.g. find='excerpt' targets the excerpt macro block), 5) heading section (e.g. find='Training Status' targets from that heading to the next same-level heading). For structured macros (excerpt, panel, status, etc.), pass the macro name as `find` — this is more reliable than text matching.",
        "input_schema": {"type": "object", "properties": {
            "page_id": {"type": "string", "description": "Confluence page ID (numeric)"},
            "find": {"type": "string", "description": "Anchor to locate. Can be: plain text, exact HTML, a Confluence macro name (e.g. 'excerpt', 'panel', 'info'), or a heading title (e.g. 'Training Status'). Macro and heading matching are the most reliable for structured pages."},
            "content": {"type": "string", "description": "The new HTML content to insert or replace with."},
            "mode": {"type": "string", "enum": ["replace", "insert_after", "insert_before", "append"], "description": "How to apply the edit. replace: swap find with content. insert_after: keep find, add content after it. insert_before: add content before find. append: ignore find, add content to end of page.", "default": "insert_after"},
            "title": {"type": "string", "description": "New title (optional — keeps current if omitted)"},
        }, "required": ["page_id", "find", "content"]},
    },
    {
        "name": "confluence_open_edit_form",
        "description": "Open the edit form for an existing Confluence page. Pre-fill with current or new content. The user reviews changes and clicks Save. You MUST call read_confluence_page first to get the current version number.",
        "input_schema": {"type": "object", "properties": {
            "page_id": {"type": "string", "description": "Page ID to edit"},
            "title": {"type": "string", "description": "Current or new title"},
            "body": {"type": "string", "description": "New body in HTML"},
            "version": {"type": "integer", "description": "Current page version (from read_confluence_page result) — required for conflict detection"},
        }, "required": ["page_id", "body", "version"]},
    },
]

TOOL_STATUS = {
    "search_confluence": "📄 Searching Confluence...",
    "read_confluence_page": "📄 Reading Confluence page...",
    "create_confluence_page": "📄 Creating Confluence page...",
    "update_confluence_page": "📄 Updating Confluence page...",
    "patch_confluence_page": "📄 Patching Confluence page...",
    "list_confluence_spaces": "📄 Listing Confluence spaces...",
    "get_confluence_child_pages": "📄 Loading child pages...",
    "confluence_show_pages": "📄 Showing pages in sidebar...",
    "confluence_open_create_form": "📄 Opening create form...",
    "confluence_open_edit_form": "📄 Opening edit form...",
}


def _tool_search_confluence(query: str, limit: int = 10) -> dict:
    try:
        safe_q = query.replace('"', '\\"')
        cql = f'(title ~ "{safe_q}" OR text ~ "{safe_q}") AND type = page'
        limit = max(1, min(int(limit), 25))
        params = urllib.parse.urlencode({"cql": cql, "limit": limit})
        data = confluence_api("GET", f"content/search?{params}")
        wiki = confluence_browse_url()
        return {"results": [
            {
                "id": r.get("id", ""),
                "title": r.get("title", ""),
                "space": r.get("resultGlobalContainer", {}).get("title",
                         r.get("_expandable", {}).get("space", "").split("/")[-1] if r.get("_expandable") else ""),
                "url": f"{wiki}{r.get('_links', {}).get('webui', '')}",
                "excerpt": r.get("excerpt", "")[:300],
            }
            for r in data.get("results", [])
        ]}
    except Exception as e:
        return {"error": str(e)}


def _tool_read_confluence_page(page_id: str) -> dict:
    m = re.search(r'/pages/(\d+)', page_id)
    if m:
        page_id = m.group(1)
    page_id = page_id.strip()
    if not page_id.isdigit():
        return {"error": f"Invalid page ID: {page_id}. Provide a numeric ID or a Confluence page URL."}
    try:
        data = confluence_api("GET", f"content/{page_id}?expand=body.storage,space,version,history.lastUpdated")
        wiki = confluence_browse_url()
        body_html = data.get("body", {}).get("storage", {}).get("value", "")
        body_text = _html_to_text(body_html, max_len=4000) if body_html else "(empty page)"
        history = data.get("history", {})
        return {
            "id": data.get("id", page_id),
            "title": data.get("title", ""),
            "space": data.get("space", {}).get("name", ""),
            "space_key": data.get("space", {}).get("key", ""),
            "version": data.get("version", {}).get("number", 0),
            "url": f"{wiki}{data.get('_links', {}).get('webui', '')}",
            "content": body_text,
            "body_html": body_html,
            "last_modified": history.get("lastUpdated", {}).get("when", "") if isinstance(history.get("lastUpdated"), dict) else history.get("lastUpdated", ""),
            "last_modifier": data.get("version", {}).get("by", {}).get("displayName", ""),
        }
    except Exception as e:
        return {"error": str(e)}


def _tool_create_confluence_page(space_key: str, title: str, body: str, parent_id: str = "") -> dict:
    payload: dict = {
        "type": "page",
        "title": title,
        "space": {"key": space_key},
        "body": {"storage": {"value": body, "representation": "storage"}},
    }
    if parent_id:
        payload["ancestors"] = [{"id": parent_id}]
    data = confluence_api("POST", "content", payload)
    wiki = confluence_browse_url()
    return {
        "id": data.get("id", ""),
        "title": data.get("title", title),
        "url": f"{wiki}{data.get('_links', {}).get('webui', '')}",
    }


def _tool_update_confluence_page(page_id: str, body: str, title: str = "") -> dict:
    current = confluence_api("GET", f"content/{page_id}?expand=version,space")
    cur_version = current.get("version", {}).get("number", 1)
    cur_title = current.get("title", "")
    payload = {
        "type": "page",
        "title": title or cur_title,
        "version": {"number": cur_version + 1},
        "body": {"storage": {"value": body, "representation": "storage"}},
    }
    data = confluence_api("PUT", f"content/{page_id}", payload)
    wiki = confluence_browse_url()
    return {
        "id": data.get("id", page_id),
        "title": data.get("title", ""),
        "version": data.get("version", {}).get("number", cur_version + 1),
        "url": f"{wiki}{data.get('_links', {}).get('webui', '')}",
    }


def _tool_list_confluence_spaces(limit: int = 25) -> dict:
    all_spaces = []

    # 1. Find current user's personal space directly
    try:
        me = confluence_api("GET", "user/current")
        username = me.get("username", "") or me.get("publicName", "")
        account_id = me.get("accountId", "")
        display_name = me.get("displayName", "") or username

        # Try known personal space key formats — accountId first (Cloud), username fallback (Server)
        # Cloud accountIds have colons/dashes (712020:9d6c-...) but space keys strip them
        account_id_clean = account_id.replace(":", "").replace("-", "")
        candidates = [f"~{account_id_clean}", f"~{account_id}", f"~{username}"] if account_id else [f"~{username}"]
        for key in candidates:
            if not key or key == "~":
                continue
            try:
                ps = confluence_api("GET", f"space/{key}")
                if ps.get("key"):
                    all_spaces.append({
                        "key": ps["key"],
                        "name": f"{display_name}'s Space",
                        "type": "personal",
                    })
                    break
            except Exception:
                continue
    except Exception:
        pass

    # 2. Fetch global spaces
    try:
        data = confluence_api("GET", f"space?limit={limit}&type=global")
        for s in data.get("results", []):
            all_spaces.append({"key": s.get("key", ""), "name": s.get("name", ""), "type": "global"})
    except Exception:
        pass

    # Deduplicate by key
    seen = set()
    spaces = []
    for s in all_spaces:
        key = s.get("key", "")
        if key and key not in seen:
            seen.add(key)
            spaces.append(s)

    # Include personal space key in response even if lookup failed
    personal_key = ""
    try:
        if not any(s.get("type") == "personal" for s in spaces):
            me = confluence_api("GET", "user/current")
            account_id = me.get("accountId", "")
            username = me.get("username", "") or me.get("publicName", "")
            # Prefer accountId (Cloud, stripped) over username (Server)
            account_id_clean = account_id.replace(":", "").replace("-", "") if account_id else ""
            personal_key = f"~{account_id_clean}" if account_id_clean else (f"~{username}" if username else "")
    except Exception:
        pass

    return {
        "spaces": spaces,
        "has_more": False,
        "personal_space_key": personal_key or next((s["key"] for s in spaces if s.get("type") == "personal"), ""),
        "hint": "For personal space, use the personal_space_key value. Personal space keys are typically ~username format.",
    }


def _tool_get_confluence_child_pages(page_id: str, limit: int = 25) -> dict:
    data = confluence_api("GET", f"content/{page_id}/child/page?limit={limit}")
    wiki = confluence_browse_url()
    results = data.get("results", [])
    return {
        "parent_id": page_id,
        "children": [
            {
                "id": p.get("id", ""),
                "title": p.get("title", ""),
                "url": f"{wiki}{p.get('_links', {}).get('webui', '')}",
            }
            for p in results
        ],
        "has_more": len(results) >= limit,
        "next_start": data.get("start", 0) + len(results) if len(results) >= limit else None,
    }


def _tool_confluence_show_pages(pages: str, title: str = "Search results") -> dict:
    import json as _json
    try:
        page_list = _json.loads(pages) if isinstance(pages, str) else pages
    except Exception:
        page_list = []
    return {
        "_pane": "confluence-list",
        "data": {"pages": page_list, "title": title},
        "_user_message": f"Showing {len(page_list)} page(s) in the Confluence sidebar.",
    }


def _tool_confluence_open_create_form(space_key: str, title: str = "", body: str = "", parent_id: str = "") -> dict:
    return {
        "_pane": "confluence-create",
        "data": {"space_key": space_key, "title": title, "body": body, "parent_id": parent_id},
        "_user_message": "Page creation form opened in /confluence pane — review and click Create.",
    }


def _normalize_ws(s: str) -> str:
    """Collapse all whitespace runs to single spaces for fuzzy matching."""
    return re.sub(r'\s+', ' ', s).strip()


def _strip_tags(s: str) -> str:
    """Remove HTML tags for text-level matching."""
    return re.sub(r'<[^>]+>', '', s)


def _find_in_body(needle: str, haystack: str):
    """Smart match: macro → heading-section → exact → whitespace-normalized → text-stripped. Returns (start, end, match_type) or None."""
    # 1. Macro match first — most reliable for structured Confluence pages
    macro_match = _find_macro(needle, haystack)
    if macro_match:
        return macro_match

    # 2. Heading-section match — find a heading and capture until next same-or-higher heading
    heading_match = _find_heading_section(needle, haystack)
    if heading_match:
        return heading_match

    # 3. Exact match
    idx = haystack.find(needle)
    if idx != -1:
        return idx, idx + len(needle), "exact"

    # 4. Whitespace-normalized match
    norm_needle = _normalize_ws(needle)
    norm_hay = _normalize_ws(haystack)
    nidx = norm_hay.find(norm_needle)
    if nidx != -1:
        orig_start = _map_norm_pos(haystack, nidx)
        orig_end = _map_norm_pos(haystack, nidx + len(norm_needle))
        if orig_start is not None and orig_end is not None:
            return orig_start, orig_end, "whitespace-normalized"

    # 5. Text-stripped match (plain text from content field)
    text_needle = _normalize_ws(_strip_tags(needle))
    if len(text_needle) >= 20:
        text_hay = _strip_tags(haystack)
        norm_text_hay = _normalize_ws(text_hay)
        tidx = norm_text_hay.find(text_needle)
        if tidx != -1:
            span = _find_html_range_for_text(haystack, text_needle)
            if span:
                return span[0], span[1], "text-content"

    return None


def _find_macro(needle: str, haystack: str):
    """Match by Confluence macro name. If needle looks like a macro name (e.g. 'excerpt',
    'status', 'panel', 'info') or contains 'macro:name', find that macro block."""
    needle_lower = needle.strip().lower()
    # Direct macro name match
    macro_names = re.findall(r'ac:name="([^"]+)"', haystack)
    for name in set(macro_names):
        if needle_lower == name.lower() or needle_lower.endswith(name.lower()):
            # Find the full macro block
            pattern = re.compile(
                r'<ac:structured-macro\s[^>]*ac:name="' + re.escape(name) + r'"[^>]*>'
                r'([\s\S]*?)'
                r'</ac:structured-macro>',
                re.IGNORECASE
            )
            m = pattern.search(haystack)
            if m:
                return m.start(), m.end(), "macro"
    return None


def _find_heading_section(needle: str, haystack: str):
    """Find a heading matching the needle text, and capture from that heading to the next
    heading of equal or higher level (or end of document)."""
    needle_text = _normalize_ws(_strip_tags(needle)).lower()
    if len(needle_text) < 3:
        return None
    # Find all headings in the HTML
    try:
        heading_pat = re.compile(r'<h([1-6])[^>]*>([\s\S]*?)</h\1>', re.IGNORECASE)
        headings = list(heading_pat.finditer(haystack))
    except re.error:
        return None
    for i, hm in enumerate(headings):
        h_text = _normalize_ws(_strip_tags(hm.group(2))).lower()
        if needle_text in h_text or h_text in needle_text:
            level = int(hm.group(1))
            start = hm.start()
            # Find end: next heading of same or higher level, or end of doc
            end = len(haystack)
            for j in range(i + 1, len(headings)):
                next_level = int(headings[j].group(1))
                if next_level <= level:
                    end = headings[j].start()
                    break
            return start, end, "heading-section"
    return None


def _map_norm_pos(original: str, norm_pos: int):
    """Map a position in normalized (whitespace-collapsed) string back to original."""
    n = 0  # position in normalized
    in_ws = False
    for i, ch in enumerate(original):
        if ch in ' \t\n\r\f\v':
            if not in_ws:
                if n == norm_pos:
                    return i
                n += 1
                in_ws = True
        else:
            if n == norm_pos:
                return i
            n += 1
            in_ws = False
    if n == norm_pos:
        return len(original)
    return None


def _find_html_range_for_text(html: str, text_needle: str):
    """Find the start/end positions in the HTML that contain the given plain-text needle."""
    text_full = _strip_tags(html)
    norm_full = _normalize_ws(text_full)
    norm_needle = _normalize_ws(text_needle)
    tidx = norm_full.find(norm_needle)
    if tidx == -1:
        return None

    # Map text positions back to HTML positions by walking both in parallel
    html_positions = []  # maps text-char-index → html-char-index
    text_i = 0
    in_tag = False
    for h_i, ch in enumerate(html):
        if ch == '<':
            in_tag = True
        elif ch == '>':
            in_tag = False
            continue
        if not in_tag:
            html_positions.append(h_i)

    # Now map normalized text position back to raw text position
    raw_text_pos = 0
    norm_i = 0
    in_ws = False
    raw_start = None
    raw_end = None
    for ri, ch in enumerate(text_full):
        if ch in ' \t\n\r\f\v':
            if not in_ws:
                if norm_i == tidx and raw_start is None:
                    raw_start = ri
                if norm_i == tidx + len(norm_needle):
                    raw_end = ri
                    break
                norm_i += 1
                in_ws = True
        else:
            if norm_i == tidx and raw_start is None:
                raw_start = ri
            if norm_i == tidx + len(norm_needle):
                raw_end = ri
                break
            norm_i += 1
            in_ws = False
    if raw_start is None:
        return None
    if raw_end is None:
        raw_end = len(text_full)

    # Map raw text positions to HTML positions
    if raw_start < len(html_positions) and raw_end <= len(html_positions):
        h_start = html_positions[raw_start]
        h_end = html_positions[min(raw_end, len(html_positions) - 1)] + 1
        # Expand to include enclosing tags
        # Walk backward from h_start to find the nearest tag open
        while h_start > 0 and html[h_start - 1] != '>':
            h_start -= 1
            if html[h_start] == '<':
                break
        # Walk forward from h_end to find nearest tag close
        while h_end < len(html) and html[h_end - 1] != '>':
            h_end += 1
        return h_start, h_end

    return None


def _tool_patch_confluence_page(page_id: str, find: str, content: str, mode: str = "insert_after", title: str = "") -> dict:
    """Smart surgical edit with flexible matching and multiple modes."""
    current = confluence_api("GET", f"content/{page_id}?expand=body.storage,version,space")
    cur_version = current.get("version", {}).get("number", 1)
    cur_title = current.get("title", "")
    cur_body = current.get("body", {}).get("storage", {}).get("value", "")

    if not cur_body:
        return {"error": "Page body is empty — nothing to patch."}

    # Append mode — no matching needed
    if mode == "append":
        new_body = cur_body + content
        return _apply_patch(page_id, new_body, title or cur_title, cur_version, "appended")

    # Find the anchor in the body
    if not find:
        return {"error": "find is required for replace/insert_after/insert_before modes. Use mode='append' to add to end."}

    match = _find_in_body(find, cur_body)
    if not match:
        # Show a snippet of the page text to help the LLM
        page_text = _normalize_ws(_strip_tags(cur_body))[:500]
        # Extract available macros and headings for the hint
        macro_names = list(set(re.findall(r'ac:name="([^"]+)"', cur_body)))
        headings = [_normalize_ws(_strip_tags(m.group(2))) for m in re.finditer(r'<h[1-6][^>]*>([\s\S]*?)</h[1-6]>', cur_body)]
        return {
            "error": "Could not find the specified text (tried exact, whitespace-normalized, text-content, macro, and heading-section matching).",
            "hint": "Try using a macro name or heading title as the find value instead of page text.",
            "available_macros": macro_names[:10] if macro_names else [],
            "available_headings": headings[:15] if headings else [],
            "page_text_preview": page_text,
        }

    start, end, match_type = match

    # Check for multiple matches (exact and whitespace-normalized)
    if match_type in ("exact", "whitespace-normalized"):
        count = cur_body.count(find) if match_type == "exact" else _normalize_ws(cur_body).count(_normalize_ws(find))
        if count > 1:
            # Extract up to 3 surrounding snippets to help caller pick a unique anchor
            snippets = []
            search_in = cur_body if match_type == "exact" else _normalize_ws(cur_body)
            needle = find if match_type == "exact" else _normalize_ws(find)
            pos = 0
            while len(snippets) < 3:
                idx = search_in.find(needle, pos)
                if idx == -1:
                    break
                ctx = _strip_tags(cur_body[max(0, idx - 60):idx + len(needle) + 60])
                snippets.append(_normalize_ws(ctx).strip())
                pos = idx + 1
            return {
                "error": f"Found {count} matches — provide a longer/more unique find string so only one location matches.",
                "hint": "Use a heading name as find value (more unique), or include surrounding text to disambiguate.",
                "match_contexts": snippets,
            }

    matched_html = cur_body[start:end]

    if mode == "replace":
        new_body = cur_body[:start] + content + cur_body[end:]
    elif mode == "insert_after":
        new_body = cur_body[:end] + content + cur_body[end:]
    elif mode == "insert_before":
        new_body = cur_body[:start] + content + cur_body[start:]
    else:
        return {"error": f"Unknown mode: {mode}. Use replace, insert_after, insert_before, or append."}

    return _apply_patch(page_id, new_body, title or cur_title, cur_version, f"{mode} (matched via {match_type})")


def _apply_patch(page_id, new_body, title, cur_version, method):
    payload = {
        "type": "page",
        "title": title,
        "version": {"number": cur_version + 1},
        "body": {"storage": {"value": new_body, "representation": "storage"}},
    }
    data = confluence_api("PUT", f"content/{page_id}", payload)
    wiki = confluence_browse_url()
    return {
        "id": data.get("id", page_id),
        "title": data.get("title", ""),
        "version": data.get("version", {}).get("number", cur_version + 1),
        "url": f"{wiki}{data.get('_links', {}).get('webui', '')}",
        "patch_applied": True,
        "method": method,
    }


def _tool_confluence_open_edit_form(page_id: str, body: str, version: int, title: str = "") -> dict:
    return {
        "_pane": "confluence-edit",
        "data": {"page_id": page_id, "title": title, "body": body, "version": version},
        "_user_message": "Edit form opened in /confluence pane — review changes and click Save.",
    }


TOOL_HANDLERS = {
    "search_confluence": _tool_search_confluence,
    "read_confluence_page": _tool_read_confluence_page,
    "create_confluence_page": _tool_create_confluence_page,
    "update_confluence_page": _tool_update_confluence_page,
    "patch_confluence_page": _tool_patch_confluence_page,
    "list_confluence_spaces": _tool_list_confluence_spaces,
    "get_confluence_child_pages": _tool_get_confluence_child_pages,
    "confluence_show_pages": _tool_confluence_show_pages,
    "confluence_open_create_form": _tool_confluence_open_create_form,
    "confluence_open_edit_form": _tool_confluence_open_edit_form,
}
