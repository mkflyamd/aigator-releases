"""Pin skill — let the user pin an item to the current tab by describing it,
the same way they would from the UI: find the item via the provider's own
search, then pin it with the exact id/label/meta the UI uses.

This deliberately avoids URL→id parsing. By routing through each provider's
existing search (the same call the side panes make), the pinned `source::id`
is byte-identical to what the pane renders, so an item pinned this way also
shows as pinned when the user later navigates to it in the UI.
"""
from __future__ import annotations

SKILL_ID = "pin"
ALWAYS_ON = True  # pinning is a cheap, generic action; always available

# Sources this tool understands, mapped to the pin `source` string the UI uses
# (see _createPinBtn in web/static/third-pane.js — these must match exactly so
# pin-state is consistent between this tool and the UI).
_SUPPORTED = ("jira", "confluence", "onedrive")


TOOL_DEFS = [
    {
        "name": "pin_item",
        "description": (
            "Pin a Jira issue, Confluence page, or OneDrive file to the user's CURRENT tab "
            "by describing it — the same as if they clicked the pin button in the UI. "
            "Use this when the user says things like 'pin the auth design doc', 'pin PROJ-123 "
            "to this tab', or 'pin my Q3 planning spreadsheet'. The tool searches the provider "
            "(exactly as the side pane does) and pins the match. On a single/exact match it pins "
            "automatically; if several items match it returns candidates so you can ask the user "
            "which one. Pins are scoped to the current tab. To pin to a different tab, the user "
            "should switch tabs first."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "source": {
                    "type": "string",
                    "enum": list(_SUPPORTED),
                    "description": "Which system the item lives in: 'jira', 'confluence', or 'onedrive'.",
                },
                "query": {
                    "type": "string",
                    "description": (
                        "What to search for: a Jira issue key (e.g. 'PROJ-123'), a page/file "
                        "title or keywords (e.g. 'auth design doc', 'Q3 planning'). Use the most "
                        "specific text the user gave."
                    ),
                },
            },
            "required": ["source", "query"],
        },
    },
]


TOOL_STATUS = {
    "pin_item": "📌 Finding and pinning item...",
}


def _norm(s: str) -> str:
    return (s or "").strip().lower()


def _search(source: str, query: str) -> tuple[list[dict], str | None]:
    """Run the provider's own search and normalize results to a common shape:
    {id, label, meta}. Returns (candidates, error). `error` is set only on a
    hard failure (auth, API); an empty list with no error means 'no matches'."""
    if source == "jira":
        from skills.jira.tools import _tool_jira_search
        # Jira search takes JQL. If the query looks like an issue key (ABC-123),
        # match it directly; otherwise do a text search across summary.
        q = query.strip()
        import re as _re
        if _re.fullmatch(r"[A-Za-z][A-Za-z0-9_]+-\d+", q):
            jql = f'key = "{q.upper()}"'
        else:
            safe = q.replace('"', '\\"')
            jql = f'summary ~ "{safe}" ORDER BY updated DESC'
        res = _tool_jira_search(jql=jql, max_results=10)
        if isinstance(res, dict) and res.get("error"):
            return [], res["error"]
        out = []
        for i in res.get("issues", []):
            out.append({
                "id": i["key"],
                "label": f"{i['key']}: {i.get('summary', '')}",
                "meta": {"url": i.get("url", ""), "priority": i.get("priority", "")},
                "_match_text": [i["key"], i.get("summary", "")],
            })
        return out, None

    if source == "confluence":
        from skills.confluence.tools import _tool_search_confluence
        res = _tool_search_confluence(query=query, limit=10)
        if isinstance(res, dict) and res.get("error"):
            return [], res["error"]
        out = []
        for r in res.get("results", []):
            out.append({
                "id": r.get("id", ""),
                "label": r.get("title", ""),
                "meta": {"url": r.get("url", ""), "space": r.get("space", "")},
                "_match_text": [r.get("title", "")],
            })
        return out, None

    if source == "onedrive":
        from skills.onedrive.tools import _tool_search_onedrive_files
        res = _tool_search_onedrive_files(query=query, count=10)
        if isinstance(res, dict) and res.get("error"):
            return [], res["error"]
        out = []
        for it in res.get("items", []):
            out.append({
                "id": it.get("id", ""),
                "label": it.get("name", ""),
                "meta": {
                    "file_path": it.get("path", it.get("name", "")),
                    "web_url": it.get("url", ""),
                },
                "_match_text": [it.get("name", "")],
            })
        return out, None

    return [], f"Unsupported source '{source}'."


def _tool_pin_item(source: str, query: str, _context_id: str | None = None) -> dict:
    source = _norm(source)
    if source not in _SUPPORTED:
        return {
            "error": f"Unsupported source '{source}'.",
            "_user_message": f"I can pin from {', '.join(_SUPPORTED)} — not '{source}'.",
        }
    if not (query or "").strip():
        return {"error": "Empty query.", "_user_message": "Tell me what to pin."}

    candidates, err = _search(source, query)
    if err:
        return {"error": err, "_user_message": f"Couldn't search {source}: {err}"}

    if not candidates:
        return {
            "found": 0,
            "_user_message": f"No {source} item matched \"{query}\".",
        }

    from skills.context.state import set_pin
    cid = _context_id or "default"

    # Decide whether this is an unambiguous match. Auto-pin when there is exactly
    # one result, OR when exactly one result's id/title matches the query exactly
    # (case-insensitive) — mirrors a user spotting the obvious hit in search.
    nq = _norm(query)
    exact = [c for c in candidates
             if nq in (_norm(c["id"]),) or nq in {_norm(t) for t in c.get("_match_text", [])}]

    chosen = None
    if len(candidates) == 1:
        chosen = candidates[0]
    elif len(exact) == 1:
        chosen = exact[0]

    if chosen is not None:
        set_pin(source, chosen["id"], chosen["label"], chosen.get("meta", {}), cid)
        return {
            "pinned": True,
            "source": source,
            "id": chosen["id"],
            "label": chosen["label"],
            "_user_message": f"📌 Pinned \"{chosen['label']}\" to this tab.",
        }

    # Ambiguous — return candidates for the model to disambiguate with the user.
    shown = [{"id": c["id"], "label": c["label"], "meta": c.get("meta", {})} for c in candidates[:8]]
    return {
        "pinned": False,
        "ambiguous": True,
        "source": source,
        "candidates": shown,
        "_user_message": (
            f"Found {len(candidates)} {source} matches for \"{query}\". "
            "Which one should I pin?\n"
            + "\n".join(f"  {n+1}. {c['label']}" for n, c in enumerate(shown))
        ),
    }


TOOL_HANDLERS = {
    "pin_item": _tool_pin_item,
}
