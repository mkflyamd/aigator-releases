"""Jira skill — 17 tools."""
import json
import re
import urllib.parse
from .api import jira_api, jira_browse_url, jira_is_cloud

SKILL_ID = "jira"
ALWAYS_ON = False

DIRECT_INTENTS = [
    {
        "patterns": ["my jira", "my tickets", "jira tickets", "my issues",
                     "assigned to me", "sprint status", "my sprint",
                     "check jira", "jira board"],
        "tool": "list_jira_issues",
        "args": {"max_results": 10},
    },
]

TOOL_DEFS = [
    {
        "name": "list_jira_issues",
        "description": "List Jira tickets assigned to the user. Use when user asks about tasks, tickets, bugs, or what they need to work on.",
        "input_schema": {
            "type": "object",
            "properties": {
                "max_results": {"type": "integer", "description": "Max issues to return. Default 10.", "default": 10},
            },
            "required": [],
        },
    },
    {
        "name": "jira_get_issue",
        "description": "Get full details of a specific Jira issue by key (e.g. PLM-1234). Use when user asks about a specific ticket.",
        "input_schema": {"type": "object", "properties": {"issue_key": {"type": "string", "description": "Jira issue key e.g. PLM-1234"}}, "required": ["issue_key"]},
    },
    {
        "name": "jira_search",
        "description": "Search Jira issues using JQL. Use when user asks to find tickets matching criteria, or asks about project status.",
        "input_schema": {"type": "object", "properties": {
            "jql": {"type": "string", "description": "JQL query e.g. 'assignee = currentUser() AND status != Done'"},
            "max_results": {"type": "integer", "description": "Max results, default 20", "default": 20},
        }, "required": ["jql"]},
    },
    {
        "name": "jira_get_project_meta",
        "description": "Get available issue types and required fields for a Jira project. ALWAYS call this before jira_create_issue to discover valid issue types and any required custom fields for that specific project.",
        "input_schema": {"type": "object", "properties": {
            "project": {"type": "string", "description": "Project key e.g. ROCM, PLM, ER"},
        }, "required": ["project"]},
    },
    {
        "name": "jira_create_issue",
        "description": "Create a new Jira issue. MUST call jira_get_project_meta first to get valid issue_type and required fields for the project.",
        "input_schema": {"type": "object", "properties": {
            "project": {"type": "string", "description": "Project key e.g. ROCM"},
            "summary": {"type": "string", "description": "Issue title/summary"},
            "issue_type": {"type": "string", "description": "Must be a valid type from jira_get_project_meta"},
            "description": {"type": "string", "description": "Detailed description"},
            "priority": {"type": "string", "description": "Highest, High, Medium, Low, Lowest"},
            "extra_fields": {"type": "string", "description": "JSON string of any additional required fields e.g. '{\"customfield_123\":{\"value\":\"foo\"}}'"},
        }, "required": ["project", "summary", "issue_type"]},
    },
    {
        "name": "jira_search_user",
        "description": "Search for a Jira user by name or email to get their ID for @mentions. Always call this before jira_add_comment when the comment includes an @mention.",
        "input_schema": {"type": "object", "properties": {
            "query": {"type": "string", "description": "Name or email to search e.g. 'Chao Chen' or 'chao.chen2@example.com'"},
        }, "required": ["query"]},
    },
    {
        "name": "jira_add_comment",
        "description": "Add a comment to a Jira issue. To @mention someone, call jira_search_user first to get their accountId (Cloud) or username (Server), then include @mention_id in the comment text.",
        "input_schema": {"type": "object", "properties": {
            "issue_key": {"type": "string", "description": "Jira issue key e.g. PLM-1234"},
            "comment": {"type": "string", "description": "Comment text. To @mention someone on Cloud, use @accountId (e.g. @712020:abc-def). Get accountId from jira_search_user first. Do NOT use [~accountid:...] wiki markup — use the @accountId format only."},
        }, "required": ["issue_key", "comment"]},
    },
    {
        "name": "jira_update_issue",
        "description": "Update fields of a Jira issue. Supports standard fields (summary, priority, assignee, labels, description, components, issue_type) and arbitrary custom fields via extra_fields JSON. To change issue type, pass issue_type AND all fields required by the new type together in the same call (use jira_get_project_meta to find required fields). Use when user asks to change or update a ticket.",
        "input_schema": {"type": "object", "properties": {
            "issue_key":   {"type": "string", "description": "Jira issue key e.g. ROCM-4005"},
            "summary":     {"type": "string", "description": "New summary/title"},
            "issue_type":  {"type": "string", "description": "New issue type — pass the numeric ID from jira_get_project_meta (e.g. '10001') for reliability, or the exact name as fallback. Must include all required fields for the new type in the same call."},
            "priority":    {"type": "string", "description": "Priority name e.g. P1: High, Medium, Low"},
            "assignee":    {"type": "string", "description": "Assignee username or account ID"},
            "labels":      {"type": "string", "description": "Comma-separated labels. Prefix with + to append (e.g. '+bug,+urgent'), - to remove (e.g. '-wontfix'), or plain to replace all."},
            "description": {"type": "string", "description": "New description"},
            "components":  {"type": "string", "description": "Comma-separated component names or IDs e.g. 'Backend,Frontend' or '10248,10249'"},
            "extra_fields": {"type": "string", "description": "JSON object of additional fields to set, e.g. '{\"customfield_10020\":{\"id\":\"10036\"},\"customfield_10030\":\"some value\"}'. Use jira_get_project_meta to discover field keys."},
        }, "required": ["issue_key"]},
    },
    {
        "name": "jira_transition",
        "description": "Move a Jira issue to a new status/workflow state (e.g. In Progress, Done, Discarded). Use when user asks to close, start, resolve, discard, or change status of a ticket. Some transitions require a comment — include one if the user provides a reason.",
        "input_schema": {"type": "object", "properties": {
            "issue_key": {"type": "string", "description": "Jira issue key e.g. ROCM-1234"},
            "transition_name": {"type": "string", "description": "Status name e.g. 'In Progress', 'Discarded', 'Closed'"},
            "comment": {"type": "string", "description": "Optional comment — required by some workflows (e.g. Discarded)"},
        }, "required": ["issue_key", "transition_name"]},
    },
    {
        "name": "jira_link_issues",
        "description": "Link two Jira issues together. Use when user asks to link, block, or relate tickets.",
        "input_schema": {"type": "object", "properties": {
            "issue_key": {"type": "string", "description": "Source issue key"},
            "other_key": {"type": "string", "description": "Target issue key"},
            "link_type": {"type": "string", "description": "Blocks, Relates, Duplicates, Clones. Default Relates", "default": "Relates"},
        }, "required": ["issue_key", "other_key"]},
    },
    {
        "name": "jira_get_issue_links",
        "description": "Get all links (related, blocks, duplicates) for a Jira issue.",
        "input_schema": {
            "type": "object",
            "properties": {
                "issue_key": {"type": "string", "description": "Issue key (e.g. PROJ-123)"},
            },
            "required": ["issue_key"],
        },
    },
    {
        "name": "jira_add_remote_link",
        "description": "Add an external URL link to a Jira issue (e.g. link to a PR, doc, or dashboard).",
        "input_schema": {
            "type": "object",
            "properties": {
                "issue_key": {"type": "string", "description": "Issue key"},
                "url": {"type": "string", "description": "URL to link"},
                "title": {"type": "string", "description": "Link title/label"},
            },
            "required": ["issue_key", "url", "title"],
        },
    },
    {
        "name": "jira_get_epic_children",
        "description": "Get all child issues of a Jira epic. Use when the user asks to see stories/tasks under an epic.",
        "input_schema": {"type": "object", "properties": {
            "epic_key": {"type": "string", "description": "Epic issue key e.g. PLM-100"},
            "max_results": {"type": "integer", "description": "Max results, default 50", "default": 50},
        }, "required": ["epic_key"]},
    },
    {
        "name": "jira_unlink_issues",
        "description": "Remove a link between two Jira issues. Use jira_get_issue_links first to find the link ID.",
        "input_schema": {"type": "object", "properties": {
            "link_id": {"type": "string", "description": "Issue link ID (from jira_get_issue_links)"},
        }, "required": ["link_id"]},
    },
    {
        "name": "jira_list_link_types",
        "description": "List all available issue link types (Blocks, Relates, Duplicates, etc.).",
        "input_schema": {"type": "object", "properties": {}, "required": []},
    },
    {
        "name": "jira_list_fields",
        "description": "List all fields available in this Jira instance, including custom fields. Use this to discover the correct customfield_XXXXX key for fields like Severity, Steps to Reproduce, Story Points, etc. Returns field id, name, and whether it's custom. Filter by name with the query parameter.",
        "input_schema": {"type": "object", "properties": {
            "query": {"type": "string", "description": "Optional filter — only return fields whose name contains this string (case-insensitive). E.g. 'severity' or 'steps'"},
        }, "required": []},
    },
    {
        "name": "jira_open_create_form",
        "description": (
            "Open the Jira ticket creation form in the sidebar for user review. "
            "Call this INSTEAD OF jira_create_issue when the user asks to create a ticket. "
            "Pre-fill everything you know. The tool returns unfilled_required_fields — "
            "ask the user for those values in chat, then call jira_update_form_fields to fill them in. "
            "Use extra_fields (JSON) to pre-fill custom fields by key."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "project": {"type": "string", "description": "Project key e.g. ROCM"},
                "summary": {"type": "string", "description": "Pre-filled ticket summary"},
                "issue_type": {"type": "string", "description": "Pre-selected issue type e.g. 'Task', 'Bug', 'Story'"},
                "description": {"type": "string", "description": "Pre-filled description"},
                "priority": {"type": "string", "description": "Pre-selected priority"},
                "extra_fields": {"type": "string", "description": "JSON object of custom field pre-fills e.g. '{\"duedate\":\"2026-05-01\",\"customfield_10511\":\"4\"}'"},
            },
            "required": ["project"],
        },
    },
    {
        "name": "jira_update_form_fields",
        "description": (
            "Update fields in the already-open Jira create form. "
            "Call this after the user provides values for required fields in chat. "
            "Pass field key-value pairs as a JSON object."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "fields": {"type": "string", "description": "JSON object of field updates e.g. '{\"duedate\":\"2026-05-01\",\"customfield_10511\":\"4\"}'"},
            },
            "required": ["fields"],
        },
    },
    {
        "name": "jira_show_issues",
        "description": (
            "Update the Jira sidebar left column with a list of issues. "
            "Call this after jira_search when the user searches for issues from the sidebar, "
            "to stream results back into the sidebar without leaving the create form. "
            "Pass the issues array from jira_search as a JSON string."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "issues": {"type": "string", "description": "JSON string of issues array from jira_search result"},
                "title": {"type": "string", "description": "Label for the list e.g. 'Search results' or 'My open bugs'"},
            },
            "required": ["issues"],
        },
    },
    {
        "name": "jira_get",
        "description": (
            "Make a raw read-only GET request to any Jira REST API endpoint. "
            "Use this freely for introspection — editmeta, createmeta, field schemas, transitions, watchers, "
            "changelog, or any endpoint not covered by the specific tools. "
            "Prefer this over guessing: when a specific tool fails with an unexpected error, "
            "call jira_get first to inspect the issue's current state or field metadata before retrying. "
            "Examples: 'issue/ROCM-123/editmeta' (what fields can be edited), "
            "'issue/ROCM-123/transitions' (available status changes), "
            "'field' (all field IDs), 'priority' (valid priority IDs). "
            "The base URL and auth are injected automatically — pass only the path after /rest/api/3/."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "API path — just the endpoint, e.g. 'issue/ROCM-123/editmeta' or 'filter/15740'. Do NOT include /rest/api/2/ or /rest/api/3/ — those are added automatically."},
                "query_params": {"type": "object", "description": "Optional query parameters e.g. {\"expand\": \"names\", \"fields\": \"summary,status\"}", "default": {}},
            },
            "required": ["path"],
        },
    },
    {
        "name": "jira_mutate",
        "description": (
            "Make a raw POST, PUT, PATCH, or DELETE request to any Jira REST API endpoint. "
            "Use only when no specific tool covers the operation. "
            "Always call jira_get to inspect the resource first — especially editmeta before field updates. "
            "Error responses are returned verbatim so you can read the exact Jira error and self-correct. "
            "Never use DELETE without confirming the exact resource key with the user first. "
            "The base URL and auth are injected automatically — pass only the path after /rest/api/3/."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "method": {"type": "string", "enum": ["POST", "PUT", "PATCH", "DELETE"], "description": "HTTP method"},
                "path": {"type": "string", "description": "API path — just the endpoint, e.g. 'issue/ROCM-123'. Do NOT include /rest/api/2/ or /rest/api/3/ — those are added automatically."},
                "body": {"type": "object", "description": "Request body as a JSON object", "default": {}},
            },
            "required": ["method", "path"],
        },
    },
]

TOOL_STATUS = {
    "list_jira_issues": "🎫 Loading Jira tickets...",
    "jira_get_issue": "🎫 Fetching Jira issue...",
    "jira_search": "🔍 Searching Jira...",
    "jira_get_project_meta": "🔍 Checking project issue types...",
    "jira_create_issue": "✏️ Creating Jira issue...",
    "jira_search_user": "🔍 Searching Jira users...",
    "jira_add_comment": "💬 Adding comment...",
    "jira_update_issue": "✏️ Updating Jira issue...",
    "jira_transition": "🔄 Transitioning issue...",
    "jira_link_issues": "🔗 Linking issues...",
    "jira_get_issue_links": "🔗 Fetching issue links...",
    "jira_add_remote_link": "🔗 Adding remote link...",
    "jira_get_epic_children": "🎫 Loading epic children...",
    "jira_unlink_issues": "🔗 Removing issue link...",
    "jira_list_link_types": "🔗 Listing link types...",
    "jira_list_fields": "🔍 Discovering field keys...",
    "jira_open_create_form": "🎫 Opening ticket form...",
    "jira_update_form_fields": "🎫 Updating form fields...",
    "jira_show_issues": "🔍 Loading issues...",
    "jira_get": "🔍 Querying Jira API...",
    "jira_mutate": "✏️ Calling Jira API...",
}


# ── Handler implementations ────────────────────────────────────────

def _sanitize_jql(jql: str) -> str:
    """Quote unquoted multi-word string values in JQL.

    LLMs frequently emit `project = Blue Ocean` instead of `project = "Blue Ocean"`.
    Jira's parser treats the second word as a stray token and raises a parse error.
    This wraps unquoted multi-word values that follow = or != in double quotes.
    """
    def _quote(m: re.Match) -> str:
        op, val, tail = m.group(1), m.group(2).strip(), m.group(3)
        # Skip already-quoted values, numbers, function calls (contain parens), single words
        if val.startswith(('"', "'")) or '(' in val or ' ' not in val:
            return m.group(0)
        return f'{op}"{val}"{tail}'

    # Match: (= or !=) <unquoted value not containing quotes/parens> (AND|OR|ORDER|end)
    return re.sub(
        r'([!=]=?\s+)([^"\'()\n,\[\]]+?)(\s+(?:AND|OR|ORDER\s+BY)\b|\s*$)',
        _quote, jql, flags=re.IGNORECASE
    )


def _jira_search_post(jql: str, max_results: int = 20, fields: list | None = None) -> dict:
    """POST /search/jql on Cloud (v3); falls back to POST /search on Server (v2)."""
    from .api import jira_is_cloud
    if fields is None:
        fields = ["summary", "status", "priority"]
    jql = _sanitize_jql(jql)
    max_results = max(1, max_results)  # Jira rejects maxResults < 1
    if jira_is_cloud():
        return jira_api("POST", "search/jql", {"jql": jql, "maxResults": max_results, "fields": fields})
    else:
        return jira_api("POST", "search", {"jql": jql, "maxResults": max_results, "fields": fields})


def _tool_list_jira_issues(max_results: int = 10) -> dict:
    try:
        data = _jira_search_post("assignee = currentUser() ORDER BY updated DESC", max_results=max_results)
        return {"issues": [
            {
                "key": i["key"],
                "summary": i["fields"].get("summary", ""),
                "status": i["fields"].get("status", {}).get("name", ""),
                "priority": (i["fields"].get("priority") or {}).get("name", ""),
                "url": f"{jira_browse_url()}/browse/{i['key']}",
            }
            for i in data.get("issues", [])
        ]}
    except Exception as e:
        return {"error": str(e)}


def _adf_to_text(node, depth=0) -> str:
    """Recursively extract plain text from Atlassian Document Format (ADF) nodes."""
    if not node:
        return ""
    if isinstance(node, str):
        return node
    if not isinstance(node, dict):
        return ""
    node_type = node.get("type", "")
    text = node.get("text", "")
    if text:
        marks = node.get("marks", [])
        # Wrap code marks
        if any(m.get("type") == "code" for m in marks):
            text = f"`{text}`"
        return text
    children = node.get("content", [])
    parts = [_adf_to_text(c, depth + 1) for c in children]
    joined = "".join(parts)
    # Add newlines for block-level nodes
    if node_type in ("paragraph", "heading", "bulletList", "orderedList", "blockquote", "codeBlock", "rule"):
        return joined.strip() + "\n"
    if node_type == "listItem":
        return "• " + joined.strip() + "\n"
    if node_type == "hardBreak":
        return "\n"
    return joined


def _tool_jira_get_issue(issue_key: str) -> dict:
    data = jira_api("GET", f"issue/{issue_key}?fields=*all&expand=names")
    f = data.get("fields", {})
    field_names = data.get("names", {})  # maps customfield_XXXXX -> human-readable name
    # Description: Jira Cloud returns ADF (dict), Jira Server returns plain string
    raw_desc = f.get("description") or ""
    if isinstance(raw_desc, dict):
        description = _adf_to_text(raw_desc).strip()[:2000]
    else:
        description = str(raw_desc).strip()[:2000]
    # Comments: most recent 5
    comments_raw = (f.get("comment") or {}).get("comments", [])[-5:]
    comments = []
    for c in comments_raw:
        body = c.get("body") or ""
        if isinstance(body, dict):
            body = _adf_to_text(body).strip()[:400]
        else:
            body = str(body).strip()[:400]
        comments.append({
            "author": (c.get("author") or {}).get("displayName", ""),
            "created": (c.get("created") or "")[:10],
            "body": body,
        })
    # Collect non-null custom fields with human-readable names
    custom_fields: dict = {}
    for field_id, value in f.items():
        if not field_id.startswith("customfield_") or value is None or value == [] or value == "":
            continue
        label = field_names.get(field_id, field_id)
        if isinstance(value, dict):
            display = value.get("value") or value.get("name") or value.get("displayName") or str(value)
        elif isinstance(value, list):
            display = [
                (v.get("value") or v.get("name") or v.get("displayName") or str(v)) if isinstance(v, dict) else str(v)
                for v in value
            ]
        else:
            display = value
        custom_fields[label] = display
    return {
        "key": data.get("key", issue_key),
        "summary": f.get("summary", ""),
        "status": f.get("status", {}).get("name", ""),
        "priority": (f.get("priority") or {}).get("name", ""),
        "assignee": (f.get("assignee") or {}).get("displayName", "Unassigned"),
        "reporter": (f.get("reporter") or {}).get("displayName", ""),
        "type": f.get("issuetype", {}).get("name", ""),
        "labels": f.get("labels", []),
        "components": [c.get("name", "") for c in f.get("components", [])],
        "fix_versions": [v.get("name", "") for v in f.get("fixVersions", [])],
        "description": description,
        "comments": comments,
        "created": f.get("created", "")[:10],
        "updated": f.get("updated", "")[:10],
        "url": f"{jira_browse_url()}/browse/{data.get('key', issue_key)}",
        "custom_fields": custom_fields,
    }


def _tool_jira_search(jql: str, max_results: int = 20) -> dict:
    data = _jira_search_post(jql, max_results=max_results, fields=["summary", "status", "priority", "assignee"])
    return {"total": data.get("total", 0), "issues": [
        {
            "key": i["key"],
            "summary": i["fields"].get("summary", ""),
            "status": i["fields"].get("status", {}).get("name", ""),
            "priority": (i["fields"].get("priority") or {}).get("name", ""),
            "assignee": (i["fields"].get("assignee") or {}).get("displayName", "Unassigned"),
            "url": f"{jira_browse_url()}/browse/{i['key']}",
        }
        for i in data.get("issues", [])
    ]}


def _tool_jira_get_project_meta(project: str) -> dict:
    data = jira_api("GET", f"issue/createmeta?projectKeys={project}&expand=projects.issuetypes.fields")
    projects = data.get("projects", [])
    if not projects:
        return {"error": f"Project '{project}' not found or no create permission."}
    p = projects[0]
    issue_types = []
    for it in p.get("issuetypes", []):
        required_fields = []
        for fname, fdata in it.get("fields", {}).items():
            # Include required fields + date fields (often required by workflow validators
            # even when not marked required in field config)
            schema = fdata.get("schema", {})
            is_date = schema.get("type") == "date" or fname == "duedate"
            is_required = fdata.get("required") or is_date
            if is_required and fname not in ("project", "issuetype", "summary"):
                allowed_values = []
                for v in fdata.get("allowedValues", []):
                    # Prefer id; fall back to value key used by some field types
                    vid = v.get("id") or v.get("value") or ""
                    vname = v.get("name") or v.get("value") or ""
                    if vname:
                        allowed_values.append({"id": vid, "name": vname})
                required_fields.append({"key": fname, "name": fdata.get("name", fname),
                                         "type": schema.get("type", ""),
                                         "system": schema.get("system", fname),
                                         "required": bool(fdata.get("required")),
                                         "allowed": allowed_values})
        issue_types.append({"name": it.get("name", ""), "id": it.get("id", ""),
                            "subtask": it.get("subtask", False),
                            "required_fields": required_fields})
    return {"project": project, "issue_types": issue_types}


def _tool_jira_create_issue(project: str, summary: str, issue_type: str,
                             description: str = "", priority: str = "", extra_fields: str = "") -> dict:
    # Human-in-the-loop guard: direct creation is not allowed.
    # Always route through jira_open_create_form so the user can review before submitting.
    return {
        "error": "Direct ticket creation is disabled. Call jira_open_create_form instead so the user can review the ticket before it is created.",
        "action": "Call jira_get_project_meta then jira_open_create_form with the same arguments.",
    }


def _tool_jira_search_user(query: str) -> dict:
    is_cloud = jira_is_cloud()
    if is_cloud:
        # Cloud: /rest/api/3/user/search returns accountId
        results = jira_api("GET", f"user/search?query={urllib.parse.quote(query)}&maxResults=5", api_version="3")
        return {"users": [
            {"display_name": u.get("displayName", ""),
             "account_id": u.get("accountId", ""),
             "email": u.get("emailAddress", ""),
             "mention_id": u.get("accountId", ""),
             "mention_hint": f"Use accountId '{u.get('accountId','')}' in comment"}
            for u in (results if isinstance(results, list) else [])
        ]}
    else:
        # Server: /rest/api/2/user/search returns username / name
        results = jira_api("GET", f"user/search?username={urllib.parse.quote(query)}&maxResults=5")
        return {"users": [
            {"display_name": u.get("displayName", ""),
             "username": u.get("name", ""),
             "email": u.get("emailAddress", ""),
             "mention_id": u.get("name", ""),
             "mention_hint": f"Use @{u.get('name','')} in comment"}
            for u in (results if isinstance(results, list) else [])
        ]}


def _build_adf_comment(text: str) -> dict:
    """Convert plain text with @accountId or [~accountid:...] tokens to ADF.

    Accepts two mention formats so the LLM can use either:
      @712020:abc-123-def   (preferred)
      [~accountid:712020:abc-123-def]  (wiki markup — also accepted)
    Both are converted to ADF mention nodes so Jira sends real notifications.
    Multi-line text is preserved as separate paragraph nodes.
    """
    _MENTION_RE = re.compile(
        r'@([A-Za-z0-9:\-_.]+)'              # @accountId
        r'|\[~accountid:([A-Za-z0-9:\-_.]+)\]'  # [~accountid:...] wiki markup
        , re.IGNORECASE
    )

    def _para(line: str) -> dict:
        inline_nodes = []
        pos = 0
        for m in _MENTION_RE.finditer(line):
            if m.start() > pos:
                inline_nodes.append({"type": "text", "text": line[pos:m.start()]})
            account_id = m.group(1) or m.group(2)
            inline_nodes.append({
                "type": "mention",
                "attrs": {"id": account_id, "text": f"@{account_id}"}
            })
            pos = m.end()
        if pos < len(line):
            inline_nodes.append({"type": "text", "text": line[pos:]})
        return {"type": "paragraph", "content": inline_nodes or [{"type": "text", "text": ""}]}

    paragraphs = [_para(line) for line in text.split("\n")]
    return {"version": 1, "type": "doc", "content": paragraphs}


# Jira Cloud (API v3) requires rich-text fields like `description` to be ADF
# objects, not plain strings — sending a string yields HTTP 400
# "Operation value must be an Atlassian Document". The comment ADF builder is
# general (mention-aware, multi-line) and works for descriptions too.
_build_adf_doc = _build_adf_comment


def _tool_jira_add_comment(issue_key: str, comment: str) -> dict:
    is_cloud = jira_is_cloud()
    if is_cloud:
        # Cloud: use ADF v3 so @mentions are functional
        body = _build_adf_comment(comment)
        jira_api("POST", f"issue/{issue_key}/comment", {"body": body}, api_version="3")
    else:
        # Server: wiki markup — @username becomes [~username]
        def _to_wiki_mention(m):
            return f"[~{m.group(1)}]"
        wiki_comment = re.sub(r'@([A-Za-z0-9._\-]+)', _to_wiki_mention, comment)
        jira_api("POST", f"issue/{issue_key}/comment", {"body": wiki_comment})
    return {"commented": True, "issue_key": issue_key}


def _tool_jira_update_issue(issue_key: str, summary: str = "", priority: str = "",
                             assignee: str = "", labels: str = "", description: str = "",
                             components: str = "", issue_type: str = "", extra_fields: str = "") -> dict:
    fields: dict = {}
    if issue_type:
        # Check editmeta first — if issuetype is not an editable field on this issue,
        # the update will always fail regardless of the value passed.
        try:
            editmeta = jira_api("GET", f"issue/{issue_key}/editmeta")
            editable_fields = editmeta.get("fields", {})
            if "issuetype" not in editable_fields:
                return {
                    "error": (
                        f"Cannot change issue type on {issue_key}: 'issuetype' is not listed "
                        f"as an editable field in Jira's editmeta response. "
                        f"Editable fields found: {list(editable_fields.keys())[:10]}. "
                        f"This is a Jira screen/workflow configuration restriction — "
                        f"use the UI Move wizard or recreate the ticket as the target type."
                    )
                }
        except Exception as e:
            # editmeta failed — report it rather than silently proceeding to a doomed update
            return {
                "error": (
                    f"Could not check editmeta for {issue_key} before attempting issue type change: {e}. "
                    f"Aborting to avoid a known-failing update. "
                    f"Call jira_get('issue/{issue_key}/editmeta') directly to diagnose."
                )
            }
        # Use id if numeric (from project meta), name otherwise
        fields["issuetype"] = {"id": issue_type} if issue_type.isdigit() else {"name": issue_type}
    if summary:
        fields["summary"] = summary
    if priority:
        fields["priority"] = {"name": priority}
    if assignee:
        if jira_is_cloud():
            fields["assignee"] = {"accountId": assignee}
        else:
            fields["assignee"] = {"name": assignee}
    if labels:
        new_labels = [l.strip() for l in labels.split(",") if l.strip()]
        # Prefix with + to append, - to remove, or plain to replace
        if all(l.startswith('+') for l in new_labels):
            # Append mode: merge with existing labels
            try:
                current = jira_api("GET", f"issue/{issue_key}?fields=labels")
                existing = current.get("fields", {}).get("labels", [])
                merged = list(set(existing + [l.lstrip('+') for l in new_labels]))
                fields["labels"] = merged
            except Exception:
                fields["labels"] = [l.lstrip('+') for l in new_labels]
        elif all(l.startswith('-') for l in new_labels):
            # Remove mode: remove from existing labels
            try:
                current = jira_api("GET", f"issue/{issue_key}?fields=labels")
                existing = current.get("fields", {}).get("labels", [])
                to_remove = {l.lstrip('-') for l in new_labels}
                fields["labels"] = [l for l in existing if l not in to_remove]
            except Exception:
                fields["labels"] = []
        else:
            # Replace mode
            fields["labels"] = [l.lstrip('+') for l in new_labels]
    if description:
        fields["description"] = _build_adf_doc(description) if jira_is_cloud() else description
    if components:
        comp_list = []
        for c in components.split(","):
            c = c.strip()
            if c.isdigit():
                comp_list.append({"id": c})
            else:
                comp_list.append({"name": c})
        fields["components"] = comp_list
    # Merge any extra/custom fields
    if extra_fields:
        try:
            extra = json.loads(extra_fields)
            if isinstance(extra, dict):
                fields.update(extra)
        except json.JSONDecodeError:
            return {"error": f"extra_fields is not valid JSON: {extra_fields[:100]}"}
    if not fields:
        return {"error": "No fields to update"}
    try:
        jira_api("PUT", f"issue/{issue_key}", {"fields": fields})
    except RuntimeError as e:
        return {"error": f"Update failed: {e}"}
    # Read back to confirm fields actually persisted — do not claim success without evidence
    try:
        verify = jira_api("GET", f"issue/{issue_key}?fields=*all")
        vf = verify.get("fields", {})
        confirmed: dict = {}
        rejected: dict = {}
        for k, v in fields.items():
            actual = vf.get(k)
            # Normalize for comparison: {"name": "X"} → "X", {"accountId": "Y"} → "Y"
            sent_val = v.get("name") or v.get("accountId") or v.get("id") or v if not isinstance(v, dict) else str(v)
            actual_val = (actual or {}).get("name") or (actual or {}).get("accountId") or (actual or {}).get("id") or actual if isinstance(actual, dict) else actual
            if actual_val and str(sent_val).lower() in str(actual_val).lower():
                confirmed[k] = actual_val
            else:
                rejected[k] = {"sent": sent_val, "actual": actual_val}
        result: dict = {"updated": True, "issue_key": issue_key, "confirmed": confirmed}
        if rejected:
            result["warning"] = "Some fields did not persist in Jira (likely screen scheme restriction)"
            result["not_updated"] = rejected
        return result
    except Exception:
        # Verification failed but write may have succeeded — be honest about uncertainty
        return {"updated": True, "issue_key": issue_key, "fields_changed": list(fields.keys()),
                "warning": "Could not verify fields persisted — check Jira directly"}


def _tool_jira_transition(issue_key: str, transition_name: str, comment: str = "") -> dict:
    # Expand fields so we can detect required fields (like resolution)
    transitions = jira_api("GET", f"issue/{issue_key}/transitions?expand=transitions.fields")
    match = None
    for t in transitions.get("transitions", []):
        if t.get("name", "").lower() == transition_name.lower():
            match = t
            break
    if not match:
        avail = [t.get("name") for t in transitions.get("transitions", [])]
        return {"error": f"Transition '{transition_name}' not found. Available: {avail}"}
    payload: dict = {"transition": {"id": str(match["id"])}}
    # Auto-fill required transition fields (e.g., resolution for "Done")
    fields = match.get("fields", {})
    if fields:
        payload_fields = {}
        for fname, fdata in fields.items():
            if fdata.get("required"):
                allowed = fdata.get("allowedValues", [])
                if allowed:
                    # Pick first allowed value (e.g., "Done" resolution)
                    payload_fields[fname] = {"name": allowed[0].get("name", allowed[0].get("value", ""))}
        if payload_fields:
            payload["fields"] = payload_fields
    if comment:
        payload["update"] = {"comment": [{"add": {"body": comment}}]}
    try:
        jira_api("POST", f"issue/{issue_key}/transitions", payload)
    except RuntimeError as e:
        return {"error": f"Transition failed: {e}"}
    return {"transitioned": True, "issue_key": issue_key, "new_status": transition_name}


def _tool_jira_link_issues(issue_key: str, other_key: str, link_type: str = "Relates") -> dict:
    jira_api("POST", "issueLink", {
        "type": {"name": link_type},
        "inwardIssue": {"key": other_key},
        "outwardIssue": {"key": issue_key},
    })
    return {"ok": True, "message": f"Linked {issue_key} → {other_key} ({link_type})"}


def _tool_jira_get_issue_links(issue_key: str) -> dict:
    issue = jira_api("GET", f"issue/{issue_key}?fields=issuelinks")
    links = issue.get("fields", {}).get("issuelinks", [])
    result = []
    for lnk in links:
        link_type = lnk.get("type", {}).get("name", "")
        if "outwardIssue" in lnk:
            result.append({"type": link_type, "direction": "outward", "link_id": str(lnk.get("id", "")),
                           "key": lnk["outwardIssue"]["key"],
                           "summary": lnk["outwardIssue"].get("fields", {}).get("summary", "")})
        elif "inwardIssue" in lnk:
            result.append({"type": link_type, "direction": "inward", "link_id": str(lnk.get("id", "")),
                           "key": lnk["inwardIssue"]["key"],
                           "summary": lnk["inwardIssue"].get("fields", {}).get("summary", "")})
    return {"issue_key": issue_key, "links": result}


def _tool_jira_add_remote_link(issue_key: str, url: str, title: str) -> dict:
    jira_api("POST", f"issue/{issue_key}/remotelink",
             {"object": {"url": url, "title": title}})
    return {"added": True, "issue_key": issue_key, "url": url, "title": title}


def _tool_jira_get_epic_children(epic_key: str, max_results: int = 50) -> dict:
    data = _jira_search_post(f'"Epic Link" = {epic_key} ORDER BY status ASC, priority DESC',
                             max_results=max_results,
                             fields=["summary", "status", "priority", "assignee", "issuetype"])
    browse = jira_browse_url()
    return {"epic": epic_key, "children": [
        {
            "key": i["key"],
            "type": i["fields"].get("issuetype", {}).get("name", ""),
            "summary": i["fields"].get("summary", ""),
            "status": i["fields"].get("status", {}).get("name", ""),
            "priority": (i["fields"].get("priority") or {}).get("name", ""),
            "assignee": (i["fields"].get("assignee") or {}).get("displayName", "Unassigned"),
            "url": f"{browse}/browse/{i['key']}",
        }
        for i in data.get("issues", [])
    ], "total": data.get("total", 0)}


def _tool_jira_unlink_issues(link_id: str) -> dict:
    jira_api("DELETE", f"issueLink/{link_id}")
    return {"deleted": True, "link_id": link_id}


def _tool_jira_list_link_types() -> dict:
    data = jira_api("GET", "issueLinkType")
    return {"link_types": [
        {"name": lt.get("name", ""), "inward": lt.get("inward", ""), "outward": lt.get("outward", "")}
        for lt in data.get("issueLinkTypes", [])
    ]}


def _tool_jira_list_fields(query: str = "") -> dict:
    """List all fields in the Jira instance, optionally filtered by name."""
    data = jira_api("GET", "field")
    fields_list = data if isinstance(data, list) else []
    if query:
        q = query.lower()
        fields_list = [f for f in fields_list if q in (f.get("name", "") or "").lower()]
    return {"fields": [
        {"id": f.get("id", ""), "name": f.get("name", ""), "custom": f.get("custom", False),
         "schema_type": (f.get("schema") or {}).get("type", "")}
        for f in fields_list[:50]  # Cap at 50 to avoid overwhelming context
    ]}


def _tool_jira_open_create_form(project: str, summary: str = "", issue_type: str = "",
                                description: str = "", priority: str = "",
                                extra_fields: str = "") -> dict:
    # Parse extra_fields if provided (AI can pass pre-filled values)
    parsed_extra = {}
    if extra_fields:
        try:
            parsed_extra = json.loads(extra_fields) if isinstance(extra_fields, str) else extra_fields
        except Exception:
            pass

    # Fetch project meta to return unfilled required fields to the AI
    unfilled_fields = []
    try:
        meta = _tool_jira_get_project_meta(project)
        target_type = issue_type or ""
        for it in meta.get("issue_types", []):
            if target_type and it["name"].lower() != target_type.lower():
                continue
            for f in it.get("required_fields", []):
                if f.get("required") is False:
                    continue
                fkey = f["key"]
                # Skip fields that are already provided
                if fkey in ("priority",) and priority:
                    continue
                if fkey in parsed_extra:
                    continue
                unfilled_fields.append({
                    "key": fkey,
                    "name": f["name"],
                    "type": f.get("type", "string"),
                    "allowed_values": [v["name"] for v in f.get("allowed", [])[:10]],
                })
            break  # only check the matched issue type
    except Exception:
        pass

    result = {
        "_pane": "jira-create",
        "data": {
            "project": project,
            "summary": summary,
            "issue_type": issue_type,
            "description": description,
            "priority": priority,
            "extra_fields": parsed_extra,
        },
    }
    if unfilled_fields:
        result["_user_message"] = (
            f"Form opened in /jira. There are {len(unfilled_fields)} required fields that need your input. "
            "Please provide values for the fields listed below, and I'll fill them in the form for you."
        )
        result["unfilled_required_fields"] = unfilled_fields
    return result


def _tool_jira_update_form_fields(fields: str) -> dict:
    """Update fields in the already-open Jira create form via pane signal."""
    parsed = {}
    try:
        parsed = json.loads(fields) if isinstance(fields, str) else fields
    except Exception:
        return {"error": "Invalid JSON in fields parameter"}
    return {
        "_pane": "jira-update-fields",
        "data": parsed,
        "_user_message": "Form fields updated. Please review and hit Create when ready.",
    }


def _tool_jira_show_issues(issues: str, title: str = "Search results") -> dict:
    parsed_issues = []
    if issues:
        try:
            parsed_issues = json.loads(issues)
        except Exception:
            pass
    return {
        "_pane": "jira-list",
        "data": {
            "issues": parsed_issues,
            "title": title,
        },
    }


def _tool_jira_get(path: str, query_params: dict | None = None) -> dict:
    """Raw read-only Jira API call. Returns response verbatim including error bodies."""
    full_path = path.lstrip("/")
    if query_params:
        qs = "&".join(f"{k}={v}" for k, v in query_params.items())
        full_path = f"{full_path}?{qs}"
    # Redirect GET search?jql=... to POST search/jql (v2/search removed on Cloud, CHANGE-2046)
    if full_path.startswith("search?") or full_path.startswith("search/jql"):
        import urllib.parse as _up
        parsed = _up.urlparse("?" + full_path.split("?", 1)[-1]) if "?" in full_path else _up.urlparse("")
        params = dict(_up.parse_qsl(parsed.query))
        jql = params.get("jql", "")
        max_results = max(1, int(params.get("maxResults", 50) or 50))
        fields_str = params.get("fields", "")
        fields = [f.strip() for f in fields_str.split(",")] if fields_str else None
        try:
            return jira_api("POST", "search/jql", {"jql": jql, "maxResults": max_results,
                                                    **({"fields": fields} if fields else {})})
        except RuntimeError as e:
            return {"error": str(e)}
    try:
        return jira_api("GET", full_path)
    except RuntimeError as e:
        return {"error": str(e)}


def _tool_jira_mutate(method: str, path: str, body: dict | None = None) -> dict:
    """Raw mutating Jira API call (POST/PUT/PATCH/DELETE). Returns response verbatim."""
    method = method.upper()
    if method not in {"POST", "PUT", "PATCH", "DELETE"}:
        return {"error": f"Invalid method '{method}'. Must be POST, PUT, PATCH, or DELETE."}
    try:
        result = jira_api(method, path.lstrip("/"), body or {})
        result = result if result else {"ok": True}
        # When a POST to the issue endpoint successfully creates a ticket, emit a
        # jira-issue pane signal so the detail view opens automatically in the sidebar.
        clean_path = path.lstrip("/").split("?")[0].rstrip("/")
        if method == "POST" and clean_path == "issue" and isinstance(result, dict) and result.get("key"):
            key = result["key"]
            url = f"{jira_browse_url()}/browse/{key}"
            result["_pane"] = "jira-issue"
            result["data"] = {"key": key, "url": url}
        return result
    except RuntimeError as e:
        return {"error": str(e)}


TOOL_HANDLERS = {
    "list_jira_issues": _tool_list_jira_issues,
    "jira_get_issue": _tool_jira_get_issue,
    "jira_search": _tool_jira_search,
    "jira_get_project_meta": _tool_jira_get_project_meta,
    "jira_create_issue": _tool_jira_create_issue,
    "jira_search_user": _tool_jira_search_user,
    "jira_add_comment": _tool_jira_add_comment,
    "jira_update_issue": _tool_jira_update_issue,
    "jira_transition": _tool_jira_transition,
    "jira_link_issues": _tool_jira_link_issues,
    "jira_get_issue_links": _tool_jira_get_issue_links,
    "jira_add_remote_link": _tool_jira_add_remote_link,
    "jira_get_epic_children": _tool_jira_get_epic_children,
    "jira_unlink_issues": _tool_jira_unlink_issues,
    "jira_list_link_types": _tool_jira_list_link_types,
    "jira_list_fields": _tool_jira_list_fields,
    "jira_open_create_form": _tool_jira_open_create_form,
    "jira_update_form_fields": _tool_jira_update_form_fields,
    "jira_show_issues": _tool_jira_show_issues,
    "jira_get": _tool_jira_get,
    "jira_mutate": _tool_jira_mutate,
}
