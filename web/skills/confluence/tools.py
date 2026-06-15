"""Confluence skill — tools."""
import html as _html_mod
import re
import urllib.parse
from .api import confluence_api, confluence_browse_url

try:
    from lxml import etree as _etree
except Exception:  # lxml missing — fall back to count-based balance check
    _etree = None

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
        "description": "Surgically edit a Confluence page. Reads the current body, finds the anchor, and applies the change. Use this instead of update_confluence_page for targeted edits. Matching is tried PRECISE-first: 1) exact HTML, 2) whitespace-normalized, 3) canonical (entity/self-closing/attribute-order tolerant — paste an HTML snippet copied from read_confluence_page and it will match even if &nbsp; vs space, <col/> vs <col>, or attribute order differ). If none match, FUZZY strategies are tried: 4) macro name (find='excerpt'), 5) heading section (find='Training Status'), 6) plain-text. A fuzzy match is NOT applied automatically for replace/insert_* — it returns a dry_run preview with match_location; confirm the target then resend with allow_fuzzy=true. PREFER passing an exact HTML snippet as `find` for guaranteed-correct targeting. For adding a table row, list item, or block next to a specific element, use after_local_id/before_local_id with that element's local-id (from read_confluence_page) — a precise structural anchor that needs no `find`.",
        "input_schema": {"type": "object", "properties": {
            "page_id": {"type": "string", "description": "Confluence page ID (numeric)"},
            "find": {"type": "string", "description": "Anchor to locate. BEST: an exact HTML snippet copied from read_confluence_page (matches precisely via exact/canonical). Also accepts: plain text, a macro name (e.g. 'excerpt'), or a heading title (e.g. 'Training Status') — but those match fuzzily and require allow_fuzzy=true to apply."},
            "content": {"type": "string", "description": "The new HTML content to insert or replace with."},
            "mode": {"type": "string", "enum": ["replace", "insert_after", "insert_before", "append"], "description": "How to apply the edit. replace: swap find with content. insert_after: keep find, add content after it. insert_before: add content before find. append: ignore find, add content to end of page.", "default": "insert_after"},
            "title": {"type": "string", "description": "New title (optional — keeps current if omitted)"},
            "allow_fuzzy": {"type": "boolean", "description": "Set true ONLY after reviewing a dry_run preview's match_location to confirm a fuzzy (macro/heading/text) match anchored at the intended spot. Default false — fuzzy matches return a preview instead of applying.", "default": False},
            "after_local_id": {"type": "string", "description": "Structure-aware insert: splice `content` immediately AFTER the whole element bearing this local-id (copied from a read_confluence_page result). Tables, rows, cells, list items, paragraphs and headings all carry a local-id. Precise and unambiguous — ignores `find`/`mode`. Ideal for adding a table row or list item."},
            "before_local_id": {"type": "string", "description": "Like after_local_id, but splices `content` immediately BEFORE the element with this local-id. Use only one of after_local_id / before_local_id."},
        }, "required": ["page_id", "content"]},
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


# Confluence storage-format container tags whose imbalance makes the strict
# XHTML parser fail with "Unexpected EOF" on a whole-body save. A scoped
# string-splice can leave one of these unbalanced when the find-anchor span
# started inside one element and ended inside another. We check balance BEFORE
# sending so a malformed splice never reaches Confluence as an opaque 400.
_BALANCED_TAGS = ("ac:structured-macro", "ac:rich-text-body", "ac:layout", "ac:layout-section", "ac:layout-cell")


def _tag_imbalances(html_str: str) -> dict:
    """Return {tag: net} for container tags whose open/close counts don't match.

    net > 0 means more opening than closing tags (unclosed); net < 0 means
    extra closing tags. Self-closing forms are counted as balanced. HTML
    entities and ordinary HTML tags are ignored — only the ac: containers
    that trigger EOF parse failures are checked.

    This is a coarse supplement to _structural_errors: it can name WHICH macro
    tag is unbalanced, but counting is blind to malformations that keep counts
    even (mis-nesting, unescaped < / &, broken entities). Use _structural_errors
    as the authoritative gate; use this only to add a human-readable tag hint.
    """
    out = {}
    for tag in _BALANCED_TAGS:
        esc = re.escape(tag)
        opens = len(re.findall(r'<' + esc + r'(?=[\s>])', html_str))
        selfclose = len(re.findall(r'<' + esc + r'\b[^>]*/>', html_str))
        closes = len(re.findall(r'</' + esc + r'>', html_str))
        net = (opens - selfclose) - closes
        if net != 0:
            out[tag] = net
    return out


def _build_entity_dtd() -> str:
    """Internal-DTD-subset declarations for every HTML5 named entity.

    Confluence storage format permits HTML named entities (&nbsp;, &mdash;, …)
    that bare XML does not know. Declaring them all (as numeric char refs, so
    no quoting hazards) lets a strict XML parser validate storage format without
    tripping on legitimate entities. The five predefined XML entities are left
    to the parser. Built once at import."""
    from html.entities import html5
    seen: set[str] = set()
    parts: list[str] = []
    for name, char in html5.items():
        ent = name[:-1] if name.endswith(";") else name
        if not ent or ent in seen or ent in ("lt", "gt", "amp", "quot", "apos"):
            continue
        if not (ent[0].isalpha() and ent.isalnum()):
            continue
        seen.add(ent)
        repl = "".join(f"&#{ord(c)};" for c in char)
        parts.append(f'<!ENTITY {ent} "{repl}">')
    return "".join(parts)


_ENTITY_DTD = _build_entity_dtd() if _etree is not None else ""
# ac: and ri: (and at: for templates) are the namespaces Confluence storage
# format uses. The URIs are irrelevant for well-formedness — only the prefix
# declarations matter — so any stable URI works.
_NS_DECL = (
    'xmlns:ac="http://atlassian.com/content" '
    'xmlns:ri="http://atlassian.com/resource/identifier" '
    'xmlns:at="http://atlassian.com/template"'
)
_WRAP_PREFIX = f"<!DOCTYPE root [{_ENTITY_DTD}]><root {_NS_DECL}>\n"
_WRAP_SUFFIX = "\n</root>"
_PREFIX_NEWLINES = _WRAP_PREFIX.count("\n")


def _structural_errors(html_str: str):
    """Return None if `html_str` is well-formed Confluence storage XHTML, else a
    dict describing the first parse error (message + best-effort location).

    Mirrors how Confluence's REST endpoint parses storage format: strict XML
    with ac/ri/at namespaces and HTML entities declared. Catches the failures a
    tag counter cannot — mis-nesting, unescaped `<`/`&`, broken entities — and
    pinpoints the exact offset so we can reject BEFORE the PUT instead of after
    an opaque 400. Falls back to count-based detection if lxml is unavailable.
    """
    if _etree is None:
        imb = _tag_imbalances(html_str)
        if imb:
            return {"message": f"unbalanced macro tags: {imb}", "imbalance": imb}
        return None
    wrapped = _WRAP_PREFIX + html_str + _WRAP_SUFFIX
    parser = _etree.XMLParser(resolve_entities=False, no_network=True, recover=False)
    try:
        _etree.fromstring(wrapped.encode("utf-8"), parser)
        return None
    except _etree.XMLSyntaxError as e:
        pos = getattr(e, "position", None) or (getattr(e, "lineno", 0), 0)
        line, col = pos[0], pos[1]
        orig_line = max(1, line - _PREFIX_NEWLINES)
        offset = None
        try:
            lines = html_str.split("\n")
            if orig_line - 1 < len(lines):
                offset = sum(len(l) + 1 for l in lines[: orig_line - 1]) + max(0, col - 1)
                offset = min(offset, len(html_str))
        except Exception:
            offset = None
        out = {"message": (e.msg or str(e)).strip(), "line": orig_line, "column": col}
        if offset is not None:
            out["offset"] = offset
        imb = _tag_imbalances(html_str)
        if imb:
            out["imbalance"] = imb
        return out


# Void/self-closing HTML elements that never carry a closing tag — excluded from
# the stack-based nesting scan so they don't look like unbalanced opens.
_VOID_TAGS = frozenset({
    "area", "base", "br", "col", "embed", "hr", "img", "input",
    "link", "meta", "param", "source", "track", "wbr",
})
_TAG_RE = re.compile(r'<(/?)([a-zA-Z][\w:-]*)([^>]*?)(/?)\s*>')


def _fragment_tag_counts(fragment: str) -> dict:
    """Per-tag open/close counts for the SUBMITTED content fragment.

    Returns {tag: {"open": n, "close": m}} for tags whose counts don't match.
    Counting is computed on the caller's content (not the whole page) so the
    diagnosis points at the caller's own markup. Mis-nesting with even counts
    won't show here — _find_unbalanced_anchor covers that case.
    """
    opens: dict = {}
    closes: dict = {}
    for m in _TAG_RE.finditer(fragment):
        closing, name, _attrs, selfclose = m.group(1), m.group(2).lower(), m.group(3), m.group(4)
        if name in _VOID_TAGS or selfclose:
            continue
        if closing:
            closes[name] = closes.get(name, 0) + 1
        else:
            opens[name] = opens.get(name, 0) + 1
    out = {}
    for name in set(opens) | set(closes):
        o, c = opens.get(name, 0), closes.get(name, 0)
        if o != c:
            out[name] = {"open": o, "close": c}
    return out


def _node_text_snippet(body: str, start: int, limit: int = 60) -> str:
    """Visible text starting at `start` (tags stripped), up to `limit` chars."""
    return _normalize_ws(_strip_tags(body[start:start + limit * 6]))[:limit]


def _find_unbalanced_anchor(html_str: str):
    """Stack-scan tags to name the first structurally-unbalanced element.

    Returns {"tag", "text", "reason"} for the offending node, or None. Mirrors a
    strict parser's stack: when a close tag doesn't match the open on top of the
    stack, the element on top was left unclosed (the usual mis-nesting culprit);
    anything still on the stack at end-of-input is also unclosed.
    """
    stack = []  # (name, text_start_pos)
    for m in _TAG_RE.finditer(html_str):
        closing, name, _attrs, selfclose = m.group(1), m.group(2).lower(), m.group(3), m.group(4)
        if name in _VOID_TAGS or selfclose:
            continue
        if not closing:
            stack.append((name, m.end()))
            continue
        # closing tag
        if stack and stack[-1][0] == name:
            stack.pop()
        else:
            # mismatch — the element on top of the stack was never closed
            if stack:
                culprit_name, culprit_pos = stack[-1]
                return {
                    "tag": culprit_name,
                    "text": _node_text_snippet(html_str, culprit_pos),
                    "reason": (
                        f"<{culprit_name}> opened but a </{name}> was reached before it was "
                        f"closed — it is nested one level too deep (or its closing tag is missing)."
                    ),
                }
            return {
                "tag": name,
                "text": "",
                "reason": f"orphaned </{name}> — a closing tag with no matching open.",
            }
    if stack:
        culprit_name, culprit_pos = stack[-1]
        return {
            "tag": culprit_name,
            "text": _node_text_snippet(html_str, culprit_pos),
            "reason": f"<{culprit_name}> is never closed before end of content.",
        }
    return None


def _all_parse_errors(html_str: str) -> list:
    """Full list of parser errors (recover mode), not just the first.

    Each entry: {"message", "line", "column"} with line mapped back to the
    original body. Empty if lxml is unavailable or the body parses clean.
    """
    if _etree is None:
        return []
    wrapped = _WRAP_PREFIX + html_str + _WRAP_SUFFIX
    parser = _etree.XMLParser(resolve_entities=False, no_network=True, recover=True)
    try:
        _etree.fromstring(wrapped.encode("utf-8"), parser)
    except Exception:
        pass
    errors = []
    for entry in getattr(parser, "error_log", []) or []:
        errors.append({
            "message": (entry.message or "").strip(),
            "line": max(1, (entry.line or 1) - _PREFIX_NEWLINES),
            "column": entry.column,
        })
    return errors


def _repair_suggestion(html_str: str):
    """Recover-mode reparse → balanced body, offered as a SUGGESTION only.

    Returns {"repaired_body_suggestion", "text_preserved", ["text_diff"]} or
    None. NEVER auto-committed — the caller (model or human) decides whether to
    resubmit it or escalate to confluence_open_edit_form. The text-preservation
    check lets the caller trust that the repair only moved tags, not content.
    """
    if _etree is None:
        return None
    import io
    parser = _etree.HTMLParser(recover=True)
    try:
        tree = _etree.parse(io.StringIO(html_str), parser)
    except Exception:
        return None
    root = tree.getroot()
    if root is None:
        return None
    container = root.find("body")
    if container is None:
        container = root
    repaired = (container.text or "")
    for child in container:
        repaired += _etree.tostring(child, encoding="unicode")
    if not repaired.strip():
        return None
    before = _normalize_ws(_html_to_text(html_str))
    after = _normalize_ws(_html_to_text(repaired))
    out = {"repaired_body_suggestion": repaired, "text_preserved": before == after}
    if before != after:
        from collections import Counter
        b, a = Counter(before.split()), Counter(after.split())
        removed = list((b - a).elements())[:8]
        added = list((a - b).elements())[:8]
        out["text_diff"] = {"removed": removed, "added": added}
    return out


def _structural_diagnosis(content_fragment: str, new_body: str) -> dict:
    """Assemble the structural_diagnosis payload for a refused splice.

    Distinguishes a fragment that is malformed on its own from a balanced
    fragment that the splice placed mid-element: `which_failed` is "fragment"
    when the submitted content fails a strict parse in isolation, else
    "assembly" (the splice landed inside an element). Reports per-tag imbalance
    counts for BOTH the fragment and the whole assembled body so the caller sees
    where the off-by-one actually lives, not just what they submitted.
    """
    diag: dict = {}
    if content_fragment:
        frag_err = _structural_errors(content_fragment)
        diag["fragment_well_formed"] = frag_err is None
        diag["which_failed"] = "fragment" if frag_err else "assembly"
        frag_counts = _fragment_tag_counts(content_fragment)
        if frag_counts:
            diag["fragment_tag_counts"] = frag_counts
    body_counts = _fragment_tag_counts(new_body)
    if body_counts:
        diag["body_tag_counts"] = body_counts
    anchor = _find_unbalanced_anchor(new_body)
    if anchor:
        diag["unbalanced_node"] = anchor
    errs = _all_parse_errors(new_body)
    if errs:
        diag["parse_errors"] = errs[:10]
    return diag


def _normalize_ws(s: str) -> str:
    """Collapse all whitespace runs to single spaces for fuzzy matching."""
    return re.sub(r'\s+', ' ', s).strip()


def _strip_tags(s: str) -> str:
    """Remove HTML tags for text-level matching."""
    return re.sub(r'<[^>]+>', '', s)


# --- Canonical (storage-format-tolerant) matching -------------------------
# A find string copied verbatim from read_confluence_page often fails an exact
# match because Confluence storage format differs cosmetically from what the
# caller pasted: &nbsp; vs  , <col/> vs <col>, attribute order. We tokenize
# both find and body into a canonical token stream (lowercased tag names, sorted
# entity-decoded attributes, trailing-slash dropped, entity-decoded text with
# collapsed ASCII whitespace) and match the token *subsequence*, then map the
# match back to a RAW span at token boundaries. This is a PRECISE strategy — it
# targets exactly the element the caller named, just spelling-insensitively.

_TAG_TOKEN_RE = re.compile(r'<[^>]+>')
_ATTR_RE = re.compile(r'([\w:.-]+)\s*=\s*"([^"]*)"')


def _canon_text(raw: str) -> str:
    """Decode entities and collapse ASCII whitespace; keep \\u00a0 distinct so
    a decoded &nbsp; matches a literal \\u00a0 but not a regular space."""
    decoded = _html_mod.unescape(raw)
    return re.sub(r'[ \t\n\r\f\v]+', ' ', decoded).strip()


def _canon_tag(tag: str) -> str:
    """Canonicalize one tag token: lowercase name, sort entity-decoded attrs,
    drop any trailing self-closing slash so <col/> == <col>."""
    inner = tag[1:-1].strip()
    if inner.endswith('/'):
        inner = inner[:-1].strip()
    if inner.startswith('/'):
        return '</' + inner[1:].strip().lower() + '>'
    if inner.startswith('!') or inner.startswith('?'):
        return '<' + inner + '>'  # comments / declarations — leave as-is
    parts = inner.split(None, 1)
    name = parts[0].lower()
    attrs = {}
    if len(parts) > 1:
        for am in _ATTR_RE.finditer(parts[1]):
            attrs[am.group(1).lower()] = _html_mod.unescape(am.group(2))
    attr_str = ''.join(f' {k}="{v}"' for k, v in sorted(attrs.items()))
    return f'<{name}{attr_str}>'


def _tokenize_with_spans(html: str):
    """Yield (canonical_token, raw_start, raw_end). Empty/whitespace-only text
    runs are dropped so the same content tokenizes identically regardless of
    inter-tag whitespace."""
    tokens = []
    pos = 0
    for m in _TAG_TOKEN_RE.finditer(html):
        if m.start() > pos:
            canon = _canon_text(html[pos:m.start()])
            if canon:
                tokens.append((canon, pos, m.start()))
        tokens.append((_canon_tag(m.group(0)), m.start(), m.end()))
        pos = m.end()
    if pos < len(html):
        canon = _canon_text(html[pos:])
        if canon:
            tokens.append((canon, pos, len(html)))
    return tokens


def _canonical_matches(needle: str, haystack: str):
    """All (start, end) raw spans where the needle's canonical token sequence
    occurs contiguously in the haystack."""
    n_tok = _tokenize_with_spans(needle)
    h_tok = _tokenize_with_spans(haystack)
    if not n_tok:
        return []
    n_canon = [t[0] for t in n_tok]
    h_canon = [t[0] for t in h_tok]
    out = []
    span = len(n_canon)
    for i in range(len(h_canon) - span + 1):
        if h_canon[i:i + span] == n_canon:
            out.append((h_tok[i][1], h_tok[i + span - 1][2]))
    return out


def _describe_location(haystack: str, start: int) -> dict:
    """Where in the page a match landed: nearest heading above it and the
    enclosing structured-macro / nearest ac:local-id. Helps the caller confirm
    a fuzzy match anchored where they intended before applying it."""
    loc: dict = {}
    last_heading = None
    for hm in re.finditer(r'<h([1-6])[^>]*>([\s\S]*?)</h\1>', haystack):
        if hm.start() <= start:
            last_heading = _normalize_ws(_strip_tags(hm.group(2)))
        else:
            break
    if last_heading:
        loc["nearest_heading"] = last_heading
    for mm in re.finditer(r'<ac:structured-macro\b[^>]*?ac:macro-id="([^"]+)"[^>]*>', haystack):
        if mm.start() > start:
            break
        close = haystack.find('</ac:structured-macro>', mm.end())
        if close != -1 and close >= start:
            loc["enclosing_macro_id"] = mm.group(1)
    # Confluence emits both bare `local-id` (body content) and `ac:local-id`
    # (macros and some elements) — match either, but not `data-local-id` etc.
    locals_before = list(re.finditer(r'(?<![\w:-])(?:ac:)?local-id="([^"]+)"', haystack[:start]))
    if locals_before:
        loc["nearest_local_id"] = locals_before[-1].group(1)
    return loc


# Match strategies that target exactly what the caller named vs. ones that
# infer a location and can land somewhere unintended.
_PRECISE_MATCH = {"exact", "whitespace-normalized", "canonical"}
_FUZZY_MATCH = {"macro", "heading-section", "text-content"}


def _find_in_body(needle: str, haystack: str):
    """Locate the anchor. PRECISE strategies (exact → whitespace-normalized →
    canonical) are tried before FUZZY ones (macro → heading-section →
    text-content) so a precise find is never silently captured by a fuzzy
    strategy at the wrong location. Returns (start, end, match_type) or None."""
    # --- PRECISE: target exactly what was given ---
    idx = haystack.find(needle)
    if idx != -1:
        return idx, idx + len(needle), "exact"

    norm_needle = _normalize_ws(needle)
    norm_hay = _normalize_ws(haystack)
    nidx = norm_hay.find(norm_needle)
    if nidx != -1:
        orig_start = _map_norm_pos(haystack, nidx)
        orig_end = _map_norm_pos(haystack, nidx + len(norm_needle))
        if orig_start is not None and orig_end is not None:
            return orig_start, orig_end, "whitespace-normalized"

    canon = _canonical_matches(needle, haystack)
    if canon:
        return canon[0][0], canon[0][1], "canonical"

    # --- FUZZY: infer a location; gated by allow_fuzzy at apply time ---
    macro_match = _find_macro(needle, haystack)
    if macro_match:
        return macro_match

    heading_match = _find_heading_section(needle, haystack)
    if heading_match:
        return heading_match

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


# Match `local-id` (body content) or `ac:local-id` (macros / some elements),
# but never `data-local-id`, `ac:macro-id`, etc.
_LOCAL_ID_OPEN_RE = re.compile(
    r'<([a-zA-Z][\w:-]*)\b[^>]*?(?<![\w:-])(?:ac:)?local-id="([^"]+)"[^>]*?>'
)


def _find_element_by_local_id(body: str, local_id: str):
    """Return the (start, end) raw span of the whole element bearing this
    local-id (open tag through its matching close), or None if absent, or the
    string "multiple" if more than one element carries the id.

    Confluence assigns local-id to tables, rows, cells, list items, paragraphs
    and headings, so this is a stable, structure-aware anchor across pages."""
    opens = [m for m in _LOCAL_ID_OPEN_RE.finditer(body) if m.group(2) == local_id]
    if not opens:
        return None
    if len(opens) > 1:
        return "multiple"
    m = opens[0]
    tag = m.group(1)
    open_start, open_end = m.start(), m.end()
    # Self-closing or void element — the element IS just the open tag.
    if m.group(0).rstrip().endswith("/>") or tag.lower() in _VOID_TAGS:
        return open_start, open_end
    # Walk forward to the matching close, accounting for nested same-name tags.
    depth = 1
    nested = re.compile(r'<(/?)' + re.escape(tag) + r'\b[^>]*?(/?)>', re.IGNORECASE)
    for tm in nested.finditer(body, open_end):
        if tm.group(1) == "/":
            depth -= 1
            if depth == 0:
                return open_start, tm.end()
        elif tm.group(2) != "/":
            depth += 1
    return None  # unbalanced markup — the structural guard will explain it


def _tool_patch_confluence_page(page_id: str, find: str = "", content: str = "", mode: str = "insert_after", title: str = "", allow_fuzzy: bool = False, after_local_id: str = "", before_local_id: str = "") -> dict:
    """Smart surgical edit with flexible matching and multiple modes."""
    current = confluence_api("GET", f"content/{page_id}?expand=body.storage,version,space")
    cur_version = current.get("version", {}).get("number", 1)
    cur_title = current.get("title", "")
    cur_body = current.get("body", {}).get("storage", {}).get("value", "")

    if not cur_body:
        return {"error": "Page body is empty — nothing to patch."}

    # Validate the SUBMITTED fragment in isolation before any splice. An exact
    # insert is a balance-preserving concat at a tag boundary, so a malformed
    # result can only come from a malformed fragment. Catching it here names the
    # real culprit ("your content is unbalanced") instead of letting the assembly
    # check report it as if the splice corrupted the page — which sends callers
    # into a retry spiral resubmitting the same broken fragment.
    if content:
        frag_err = _structural_errors(content)
        if frag_err:
            return {
                "patch_applied": False,
                "which_failed": "fragment",
                "error": "Your content isn't well-formed XHTML — fix the fragment before patching.",
                "fragment_error": frag_err,
                "fragment_tag_counts": _fragment_tag_counts(content),
            }

    # Append mode — no matching needed
    if mode == "append":
        new_body = cur_body + content
        return _validate_and_apply(page_id, cur_body, new_body, title or cur_title, cur_version, "appended", content_fragment=content)

    # Structure-aware insert by local-id — a precise, unambiguous anchor. Splices
    # content adjacent to the WHOLE element bearing the id (row, list item,
    # paragraph, heading, macro…). No fuzzy guessing, so no allow_fuzzy gate.
    if after_local_id and before_local_id:
        return {"error": "Pass only one of after_local_id / before_local_id, not both."}
    anchor_id = after_local_id or before_local_id
    if anchor_id:
        span = _find_element_by_local_id(cur_body, anchor_id)
        if span is None:
            local_ids = re.findall(r'(?<![\w:-])(?:ac:)?local-id="([^"]+)"', cur_body)
            return {
                "error": f"No element with local-id '{anchor_id}' found on this page.",
                "hint": "Read the page and copy a local-id from the element you want to anchor to — tables, rows, cells, list items, paragraphs and headings all carry one.",
                "available_local_ids": local_ids[:20],
            }
        if span == "multiple":
            return {"error": f"More than one element carries local-id '{anchor_id}' — cannot anchor unambiguously. Use an exact HTML find instead."}
        start, end = span
        location = _describe_location(cur_body, start)
        if after_local_id:
            new_body = cur_body[:end] + content + cur_body[end:]
            method = f"insert after local-id {anchor_id}"
        else:
            new_body = cur_body[:start] + content + cur_body[start:]
            method = f"insert before local-id {anchor_id}"
        result = _validate_and_apply(page_id, cur_body, new_body, title or cur_title, cur_version, method, content_fragment=content)
        if isinstance(result, dict):
            result.setdefault("match_type", "local-id")
            if location:
                result.setdefault("match_location", location)
        return result

    # Find the anchor in the body
    if not find:
        return {"error": "find is required for replace/insert_after/insert_before modes. Use mode='append' to add to end, or after_local_id/before_local_id to insert next to an element by its local-id."}

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

    # Check for multiple matches (precise strategies only — fuzzy strategies
    # already return a single inferred region).
    if match_type in ("exact", "whitespace-normalized"):
        count = cur_body.count(find) if match_type == "exact" else _normalize_ws(cur_body).count(_normalize_ws(find))
    elif match_type == "canonical":
        count = len(_canonical_matches(find, cur_body))
    else:
        count = 1
    if count > 1:
        # Extract up to 3 surrounding snippets to help caller pick a unique anchor
        snippets = []
        if match_type == "canonical":
            for sp_start, _sp_end in _canonical_matches(find, cur_body)[:3]:
                ctx = _strip_tags(cur_body[max(0, sp_start - 60):sp_start + 120])
                snippets.append(_normalize_ws(ctx).strip())
        else:
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

    location = _describe_location(cur_body, start)
    matched_html = cur_body[start:end]

    # Fuzzy matches can anchor in the wrong place (e.g. a heading-section or
    # macro-name match landing in a different section than intended). Never
    # auto-apply one for a destructive/insert edit — return a dry-run preview
    # with location context and require allow_fuzzy=true to proceed.
    if match_type in _FUZZY_MATCH and not allow_fuzzy:
        return {
            "patch_applied": False,
            "dry_run": True,
            "reason": (
                f"Anchor matched via fuzzy strategy '{match_type}', which infers a location and can "
                f"land somewhere other than intended. Not applying without confirmation."
            ),
            "match_type": match_type,
            "match_location": location,
            "matched_text_preview": _normalize_ws(_strip_tags(matched_html))[:300],
            "matched_html_head": matched_html[:200],
            "matched_html_tail": matched_html[-200:] if len(matched_html) > 200 else "",
            "hint": (
                "Confirm match_location is the intended target. To apply anyway, resend with "
                "allow_fuzzy=true. For a guaranteed-correct target, pass an exact HTML snippet as "
                "find (it will match via the PRECISE exact/canonical strategy)."
            ),
        }

    if mode == "replace":
        new_body = cur_body[:start] + content + cur_body[end:]
    elif mode == "insert_after":
        new_body = cur_body[:end] + content + cur_body[end:]
    elif mode == "insert_before":
        new_body = cur_body[:start] + content + cur_body[start:]
    else:
        return {"error": f"Unknown mode: {mode}. Use replace, insert_after, insert_before, or append."}

    result = _validate_and_apply(page_id, cur_body, new_body, title or cur_title, cur_version, f"{mode} (matched via {match_type})", content_fragment=content)
    if isinstance(result, dict):
        result.setdefault("match_type", match_type)
        if location:
            result.setdefault("match_location", location)
    return result


def _validate_and_apply(page_id, cur_body, new_body, title, cur_version, method, content_fragment=None):
    """Reject structurally-malformed saves before they reach Confluence.

    A whole-body PUT of storage format that isn't well-formed XHTML fails with an
    opaque parse 400 ('Unexpected EOF', 'no name', 'tag mismatch', …). We run the
    same strict parse locally first and explain whether the malformation was
    introduced by this edit (bad splice) or already present on the page — then
    steer the caller to the edit-form path instead of retrying blindly.

    On a splice failure we also return a precise structural_diagnosis (which tag
    in the SUBMITTED content is unbalanced, named with a text anchor) and a
    reviewable repaired_body_suggestion — never auto-committed.
    """
    import hashlib
    post = _structural_errors(new_body)
    if post:
        pre = _structural_errors(cur_body)
        ctx = ""
        off = post.get("offset")
        if off is not None:
            lo, hi = max(0, off - 200), min(len(new_body), off + 200)
            ctx = new_body[lo:hi]
        # Echo back exactly what was validated so the caller can confirm the
        # error pertains to THIS submission (there is no result caching — an
        # identical error across calls means the markup genuinely didn't change).
        echo = {}
        if content_fragment is not None:
            echo["submitted_content_len"] = len(content_fragment)
            echo["submitted_content_sha"] = hashlib.sha256(content_fragment.encode("utf-8")).hexdigest()[:16]
        if not pre:
            diagnosis = _structural_diagnosis(content_fragment or new_body, new_body)
            repair = _repair_suggestion(new_body)
            resp = {
                "patch_applied": False,
                "error": (
                    f"Refusing to save: the patched body is not well-formed XHTML, so Confluence "
                    f"would reject it with a parse error. Parser: {post['message']}"
                ),
                "parse_error": post,
                "context_around_offset": ctx,
                "matched_via": method,
                "hint": (
                    "This splice produced malformed storage format — see structural_diagnosis for the "
                    "exact unbalanced tag. Fix the nesting and resubmit, apply repaired_body_suggestion "
                    "(review the text_diff first — it is a SUGGESTION, not auto-saved), or use "
                    "confluence_open_edit_form for a human-reviewed rewrite."
                ),
                "suggested_next": [{
                    "skill": "confluence",
                    "tool": "confluence_open_edit_form",
                    "why": "Macro-balanced full rewrite that avoids the strict-parse failure.",
                }],
                **echo,
            }
            if diagnosis:
                resp["structural_diagnosis"] = diagnosis
            if repair:
                resp.update(repair)
            return resp
        return {
            "patch_applied": False,
            "error": (
                f"The current page is already malformed XHTML, so any whole-body API save will fail "
                f"with a parse error. Parser: {pre['message']}. This page cannot be safely patched "
                f"via the API."
            ),
            "pre_existing_error": pre,
            "hint": (
                "Use confluence_open_edit_form (the Confluence editor repairs storage format on save) "
                "or restore a clean version from Page history → Restore."
            ),
            "suggested_next": [{
                "skill": "confluence",
                "tool": "confluence_open_edit_form",
                "why": "The page is already malformed; the editor repairs storage format on save.",
            }],
            **echo,
        }
    # An assembled body identical to what's already stored is a no-op: PUTting it
    # makes Confluence return 200 with the version unchanged, which historically
    # read as a false success. Fail fast before the wasted API call (issue #79).
    if new_body == cur_body:
        return {
            "patch_applied": False,
            "reason": "no_change_detected",
            "base_version": cur_version,
            "version": cur_version,
            "method": method,
            "error": (
                "The patch would not change the page — the assembled body is identical "
                "to the current content, so nothing was saved."
            ),
            "hint": (
                "The anchor matched but the resulting body is unchanged. Pick a different "
                "anchor/content, or use mode='replace' with a full-element anchor if you "
                "meant to swap an existing element."
            ),
        }
    # The patch tool NEVER auto-opens the HITL edit form — not on success, not on
    # failure. Every failure path returns an actionable error plus a suggested_next
    # pointing at confluence_open_edit_form, which the model calls explicitly when a
    # human-reviewed rewrite is warranted. Auto-popping the form on intermediate
    # failures the model recovers from (find-not-found, fuzzy, parse errors) was the
    # source of the spurious blank-pane misfires mid-stream.
    return _apply_patch(page_id, new_body, title, cur_version, method)


def _apply_patch(page_id, new_body, title, cur_version, method):
    payload = {
        "type": "page",
        "title": title,
        "version": {"number": cur_version + 1},
        "body": {"storage": {"value": new_body, "representation": "storage"}},
    }
    try:
        data = confluence_api("PUT", f"content/{page_id}", payload)
    except RuntimeError as e:
        msg = str(e)
        result = {"patch_applied": False, "error": msg, "method": method}
        # Confluence reports parse failures as "...[row,col]". Surface the
        # bytes around `col` so the caller can see whether the malformed region
        # is inside the edit or elsewhere on the page.
        m = re.search(r'\[(\d+),(\d+)\]', msg)
        if m:
            col = int(m.group(2))
            lo, hi = max(0, col - 200), min(len(new_body), col + 200)
            result["error_offset"] = col
            result["body_length"] = len(new_body)
            result["context_around_offset"] = new_body[lo:hi]
            result["hint"] = (
                "Confluence rejected the reassembled body at the offset above. Inspect "
                "context_around_offset; if offset is near body_length the imbalance is global "
                "(a missing close tag somewhere). Use confluence_open_edit_form for a normalized save."
            )
            result["suggested_next"] = [{
                "skill": "confluence",
                "tool": "confluence_open_edit_form",
                "why": "Confluence rejected the API save; the editor normalizes storage format.",
            }]
        return result
    wiki = confluence_browse_url()
    new_version = data.get("version", {}).get("number", cur_version + 1)
    # Confluence returns 200 with the SAME version when the save normalizes to
    # byte-identical storage — a silent no-op. Trust the version, not the HTTP
    # status: if it didn't increment, the edit did not land (issue #79).
    if new_version <= cur_version:
        return {
            "patch_applied": False,
            "reason": "no_change_detected",
            "base_version": cur_version,
            "version": new_version,
            "method": method,
            "error": (
                f"Confluence accepted the request but the page version did not change "
                f"({cur_version} → {new_version}) — the edit did not land. This happens "
                f"when the submitted body normalizes to the existing content."
            ),
            "hint": (
                "Re-read the page and verify the target element; switch to mode='replace' "
                "with a full-element anchor if you meant to swap an existing element."
            ),
        }
    return {
        "id": data.get("id", page_id),
        "title": data.get("title", ""),
        "base_version": cur_version,
        "version": new_version,
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
