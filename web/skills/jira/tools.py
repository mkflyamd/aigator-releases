"""Jira skill â€” 17 tools."""

import json
import re
import urllib.parse
from urllib.parse import urlparse
from .api import jira_api, jira_browse_url, jira_is_cloud
from .mutations import (
    JiraTargetResolutionError,
    compare_jira_fields,
    resolve_builtin_target,
    resolve_target_for_context,
    select_target_for_context,
    target_selection_event,
    verified_result,
)

SKILL_ID = "jira"
ALWAYS_ON = False

_BROWSE_KEY_RE = re.compile(r"/browse/([A-Z][A-Z0-9]+-\d+)", re.IGNORECASE)


def _extract_issue_key(issue_key_or_url: str) -> str:
    """Return the bare issue key from either a key or a full Jira browse URL.

    When the user pastes a full URL like https://amd-hub.atlassian.net/browse/AIOSS-6037,
    the model may pass it as issue_key. Jira's REST API and Rovo tools both require
    the bare key (AIOSS-6037), not the full URL.
    """
    if issue_key_or_url.startswith(("http://", "https://")):
        m = _BROWSE_KEY_RE.search(issue_key_or_url)
        if m:
            return m.group(1)
    return issue_key_or_url


_TEAMS_IMAGE_HOSTS = frozenset({
    "teams.microsoft.com", "statics.teams.cdn.office.net",
    "au.statics.teams.cdn.office.net", "eu.statics.teams.cdn.office.net",
    "asm.skype.com", "sfbassets.com", "graph.microsoft.com",
})
_MAX_JIRA_ATTACHMENT_BYTES = 20 * 1024 * 1024


def _target_resolution_result(exc: JiraTargetResolutionError, context_id: str) -> dict:
    """Stop the turn and request a tab-scoped site choice when needed.

    A plain tool error lets the model keep trying alternate Jira/MCP/code
    paths.  An ambiguity is instead a UI interaction boundary: emit the
    structured picker and mark this round terminal until the user chooses.
    """
    detail = str(exc)
    if context_id and "ambiguous" in detail.lower():
        return {
            "error": "Jira site selection is required before this action can be drafted.",
            "_jira_target_selection": target_selection_event(context_id, detail),
            "_tool_outcome": {
                "category": "selection_required",
                "code": "jira_target_ambiguous",
                "retryable": False,
                "terminal": True,
                "user_message": "Choose the Jira site for this AI Gator tab to continue.",
            },
        }
    return {"error": detail}

DIRECT_INTENTS = [
    {
        "patterns": [
            "my jira",
            "my tickets",
            "jira tickets",
            "my issues",
            "assigned to me",
            "sprint status",
            "my sprint",
            "check jira",
            "jira board",
        ],
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
                "max_results": {
                    "type": "integer",
                    "description": "Max issues to return. Default 10.",
                    "default": 10,
                },
            },
            "required": [],
        },
    },
    {
        "name": "jira_get_issue",
        "description": (
            "Get a Jira issue by key or full URL. "
            "This is the primary Jira read tool — it covers ALL connected Jira sites automatically "
            "(both direct credentials and Rovo/cloud-atlassian connected sites). "
            "Always use this tool first for any Jira issue lookup regardless of which site the issue is on. "
            "Do NOT use MCP Jira tools instead of this — they are secondary fallbacks only."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "issue_key": {
                    "type": "string",
                    "description": "Jira issue key e.g. PLM-1234",
                }
            },
            "required": ["issue_key"],
        },
    },
    {
        "name": "jira_search",
        "description": "Search Jira issues using JQL. Use when user asks to find tickets matching criteria, or asks about project status.",
        "input_schema": {
            "type": "object",
            "properties": {
                "jql": {
                    "type": "string",
                    "description": "JQL query e.g. 'assignee = currentUser() AND status != Done'",
                },
                "max_results": {
                    "type": "integer",
                    "description": "Max results, default 20",
                    "default": 20,
                },
            },
            "required": ["jql"],
        },
    },
    {
        "name": "jira_get_project_meta",
        "description": "Get available issue types and required fields for a Jira project. ALWAYS call this before jira_create_issue to discover valid issue types and any required custom fields for that specific project.",
        "input_schema": {
            "type": "object",
            "properties": {
                "project": {
                    "type": "string",
                    "description": "Project key e.g. ROCM, PLM, ER",
                },
            },
            "required": ["project"],
        },
    },
    {
        "name": "jira_create_issue",
        "description": "Create a new Jira issue. MUST call jira_get_project_meta first to get valid issue_type and required fields for the project.",
        "input_schema": {
            "type": "object",
            "properties": {
                "project": {"type": "string", "description": "Project key e.g. ROCM"},
                "summary": {"type": "string", "description": "Issue title/summary"},
                "issue_type": {
                    "type": "string",
                    "description": "Must be a valid type from jira_get_project_meta",
                },
                "description": {
                    "type": "string",
                    "description": "Detailed description",
                },
                "priority": {
                    "type": "string",
                    "description": "Highest, High, Medium, Low, Lowest",
                },
                "extra_fields": {
                    "type": "string",
                    "description": 'JSON string of any additional required fields e.g. \'{"customfield_123":{"value":"foo"}}\'',
                },
            },
            "required": ["project", "summary", "issue_type"],
        },
    },
    {
        "name": "jira_search_user",
        "description": "Search for a Jira user by name or email to get their ID for @mentions. Always call this before jira_add_comment when the comment includes an @mention.",
        "input_schema": {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "Name or email to search e.g. 'Chao Chen' or 'chao.chen2@example.com'",
                },
            },
            "required": ["query"],
        },
    },
    {
        "name": "jira_add_comment",
        "description": "Add a comment to a Jira issue. To @mention someone, call jira_search_user first to get their accountId (Cloud) or username (Server), then include @mention_id in the comment text.",
        "input_schema": {
            "type": "object",
            "properties": {
                "issue_key": {
                    "type": "string",
                    "description": "Jira issue key e.g. PLM-1234",
                },
                "comment": {
                    "type": "string",
                    "description": "Comment text. To @mention someone on Cloud, use @accountId (e.g. @712020:abc-def). Get accountId from jira_search_user first. Do NOT use [~accountid:...] wiki markup â€” use the @accountId format only.",
                },
            },
            "required": ["issue_key", "comment"],
        },
    },
    {
        "name": "jira_add_watcher",
        "description": "Stage adding a resolved Jira account ID as a watcher. The user must approve and AI Gator verifies the exact account is watching the selected issue.",
        "input_schema": {
            "type": "object",
            "properties": {
                "issue_key": {"type": "string", "description": "Jira issue key or full Jira issue URL"},
                "account_id": {"type": "string", "description": "Account ID from jira_search_user"},
                "display_name": {"type": "string", "description": "Optional display name for review"},
            },
            "required": ["issue_key", "account_id"],
        },
    },
    {
        "name": "jira_stage_attachment",
        "description": "Stage attaching a user-uploaded Jira attachment. Accepts only the opaque upload ID returned by the Jira attachment staging endpoint; never pass a filesystem path.",
        "input_schema": {
            "type": "object",
            "properties": {
                "issue_key": {"type": "string", "description": "Jira issue key or full Jira issue URL"},
                "upload_id": {"type": "string", "description": "Opaque Jira attachment upload ID"},
            },
            "required": ["issue_key", "upload_id"],
        },
    },
    {
        "name": "jira_stage_teams_attachment",
        "description": "Securely stage a normal file attachment from a specific Teams chat message for Jira. Use this when the user asks to attach a Teams file to Jira. It resolves the trusted Teams attachment through OneDrive/SharePoint, snapshots bytes, and returns a Jira review draft; never use a local path.",
        "input_schema": {
            "type": "object",
            "properties": {
                "issue_key": {"type": "string", "description": "Jira issue key or full Jira issue URL"},
                "chat_id": {"type": "string", "description": "Trusted Teams chat ID from the selected/pinned message context"},
                "message_id": {"type": "string", "description": "Trusted Teams message ID containing the file"},
            },
            "required": ["issue_key", "chat_id", "message_id"],
        },
    },
    {
        "name": "jira_stage_teams_image",
        "description": "Securely stage an inline Teams-hosted image for a Jira attachment. Only use a Teams image URL returned by read_teams_chats or selected Teams context; never use a local filesystem path.",
        "input_schema": {
            "type": "object",
            "properties": {
                "issue_key": {"type": "string", "description": "Jira issue key or full Jira issue URL"},
                "image_url": {"type": "string", "description": "Trusted Teams-hosted image URL from the message body"},
                "filename": {"type": "string", "description": "Optional filename for the review card"},
            },
            "required": ["issue_key", "image_url"],
        },
    },
    {
        "name": "jira_update_issue",
        "description": "Update fields of a Jira issue. Supports standard fields (summary, priority, assignee, labels, description, components, issue_type) and arbitrary custom fields via extra_fields JSON. To change issue type, pass issue_type AND all fields required by the new type together in the same call (use jira_get_project_meta to find required fields). Use when user asks to change or update a ticket.",
        "input_schema": {
            "type": "object",
            "properties": {
                "issue_key": {
                    "type": "string",
                    "description": "Jira issue key e.g. ROCM-4005",
                },
                "summary": {"type": "string", "description": "New summary/title"},
                "issue_type": {
                    "type": "string",
                    "description": "New issue type â€” pass the numeric ID from jira_get_project_meta (e.g. '10001') for reliability, or the exact name as fallback. Must include all required fields for the new type in the same call.",
                },
                "priority": {
                    "type": "string",
                    "description": "Priority name e.g. P1: High, Medium, Low",
                },
                "assignee": {
                    "type": "string",
                    "description": "Assignee username or account ID",
                },
                "reporter": {"type": "string", "description": "Reporter account ID (Cloud) or username (Server)"},
                "parent_key": {"type": "string", "description": "Parent issue key; use for hierarchy changes"},
                "labels": {
                    "type": "string",
                    "description": "Comma-separated labels. Prefix with + to append (e.g. '+bug,+urgent'), - to remove (e.g. '-wontfix'), or plain to replace all.",
                },
                "description": {"type": "string", "description": "New description"},
                "components": {
                    "type": "string",
                    "description": "Comma-separated component names or IDs e.g. 'Backend,Frontend' or '10248,10249'",
                },
                "extra_fields": {
                    "type": "string",
                    "description": 'JSON object of additional fields to set, e.g. \'{"customfield_10020":{"id":"10036"},"customfield_10030":"some value"}\'. Use jira_get_project_meta to discover field keys.',
                },
            },
            "required": ["issue_key"],
        },
    },
    {
        "name": "jira_transition",
        "description": "Move a Jira issue to a new status/workflow state (e.g. In Progress, Done, Discarded). Use when user asks to close, start, resolve, discard, or change status of a ticket. Some transitions require a comment â€” include one if the user provides a reason.",
        "input_schema": {
            "type": "object",
            "properties": {
                "issue_key": {
                    "type": "string",
                    "description": "Jira issue key e.g. ROCM-1234",
                },
                "transition_name": {
                    "type": "string",
                    "description": "Status name e.g. 'In Progress', 'Discarded', 'Closed'",
                },
                "comment": {
                    "type": "string",
                    "description": "Optional comment â€” required by some workflows (e.g. Discarded)",
                },
            },
            "required": ["issue_key", "transition_name"],
        },
    },
    {
        "name": "jira_link_issues",
        "description": "Link two Jira issues together. Use when user asks to link, block, or relate tickets.",
        "input_schema": {
            "type": "object",
            "properties": {
                "issue_key": {"type": "string", "description": "Source issue key"},
                "other_key": {"type": "string", "description": "Target issue key"},
                "link_type": {
                    "type": "string",
                    "description": "Blocks, Relates, Duplicates, Clones. Default Relates",
                    "default": "Relates",
                },
            },
            "required": ["issue_key", "other_key"],
        },
    },
    {
        "name": "jira_get_issue_links",
        "description": "Get all links (related, blocks, duplicates) for a Jira issue.",
        "input_schema": {
            "type": "object",
            "properties": {
                "issue_key": {
                    "type": "string",
                    "description": "Issue key (e.g. PROJ-123)",
                },
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
        "input_schema": {
            "type": "object",
            "properties": {
                "epic_key": {
                    "type": "string",
                    "description": "Epic issue key e.g. PLM-100",
                },
                "max_results": {
                    "type": "integer",
                    "description": "Max results, default 50",
                    "default": 50,
                },
            },
            "required": ["epic_key"],
        },
    },
    {
        "name": "jira_unlink_issues",
        "description": "Remove a link between two Jira issues. Use jira_get_issue_links first to find the link ID.",
        "input_schema": {
            "type": "object",
            "properties": {
                "link_id": {
                    "type": "string",
                    "description": "Issue link ID (from jira_get_issue_links)",
                },
            },
            "required": ["link_id"],
        },
    },
    {
        "name": "jira_list_link_types",
        "description": "List all available issue link types (Blocks, Relates, Duplicates, etc.).",
        "input_schema": {"type": "object", "properties": {}, "required": []},
    },
    {
        "name": "jira_list_fields",
        "description": "List all fields available in this Jira instance, including custom fields. Use this to discover the correct customfield_XXXXX key for fields like Severity, Steps to Reproduce, Story Points, etc. Returns field id, name, and whether it's custom. Filter by name with the query parameter.",
        "input_schema": {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "Optional filter â€” only return fields whose name contains this string (case-insensitive). E.g. 'severity' or 'steps'",
                },
            },
            "required": [],
        },
    },
    {
        "name": "jira_open_create_form",
        "description": (
            "Stage a Jira ticket for user review via a draft approval card in chat. "
            "Call this INSTEAD OF jira_create_issue when the user asks to create a ticket. "
            "Always call jira_get_project_meta first. "
            "For assignee: always call jira_search_user first to resolve the account ID â€” never pass a display name. "
            "For parent/epic: pass the issue key (e.g. PROJ-89) in parent_key â€” do NOT hardcode customfield IDs. "
            "The draft card shows all fields for user review. User clicks 'Create issue' to submit; "
            "Gator then verifies parent and assignee actually persisted before reporting success. "
            "If required fields are missing, return them to the agent via unfilled_required_fields "
            "and collect from the user in chat before calling this tool. "
            "ITERATION: if the user asks to change any field on the draft, call this tool again with ALL fields "
            "updated â€” the old draft card is replaced automatically. Do NOT call jira_update_form_fields."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "project": {"type": "string", "description": "Project key e.g. ROCM"},
                "summary": {"type": "string", "description": "Ticket summary/title"},
                "issue_type": {
                    "type": "string",
                    "description": "Issue type from jira_get_project_meta e.g. 'Task', 'Bug', 'Story'",
                },
                "description": {"type": "string", "description": "Ticket description"},
                "priority": {"type": "string", "description": "Priority e.g. High, Medium, Low"},
                "parent_key": {
                    "type": "string",
                    "description": "Parent or epic issue key e.g. 'PROJ-89'. Do NOT hardcode field IDs.",
                },
                "assignee_account_id": {
                    "type": "string",
                    "description": "Assignee account ID from jira_search_user. Always resolve first.",
                },
                "assignee_display": {
                    "type": "string",
                    "description": "Human-readable assignee name for the draft card display.",
                },
                "extra_fields": {
                    "type": "string",
                    "description": 'JSON object of extra custom fields e.g. \'{"duedate":"2026-05-01"}\'',
                },
            },
            "required": ["project", "summary", "issue_type"],
        },
    },
    {
        "name": "jira_update_form_fields",
        "description": (
            "DEPRECATED â€” do NOT call this tool. "
            "To iterate on a Jira draft (user asks to change a field), call jira_open_create_form again "
            "with ALL fields including the updated ones. The previous draft card will be replaced automatically."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "fields": {
                    "type": "string",
                    "description": 'JSON object of field updates e.g. \'{"duedate":"2026-05-01","customfield_10511":"4"}\'',
                },
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
                "issues": {
                    "type": "string",
                    "description": "JSON string of issues array from jira_search result",
                },
                "title": {
                    "type": "string",
                    "description": "Label for the list e.g. 'Search results' or 'My open bugs'",
                },
            },
            "required": ["issues"],
        },
    },
    {
        "name": "jira_get",
        "description": (
            "Make a raw read-only GET request to any Jira REST API endpoint. "
            "Use this freely for introspection â€” editmeta, createmeta, field schemas, transitions, watchers, "
            "changelog, or any endpoint not covered by the specific tools. "
            "Prefer this over guessing: when a specific tool fails with an unexpected error, "
            "call jira_get first to inspect the issue's current state or field metadata before retrying. "
            "Examples: 'issue/ROCM-123/editmeta' (what fields can be edited), "
            "'issue/ROCM-123/transitions' (available status changes), "
            "'field' (all field IDs), 'priority' (valid priority IDs). "
            "The base URL and auth are injected automatically â€” pass only the path after /rest/api/3/."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "path": {
                    "type": "string",
                    "description": "API path â€” just the endpoint, e.g. 'issue/ROCM-123/editmeta' or 'filter/15740'. Do NOT include /rest/api/2/ or /rest/api/3/ â€” those are added automatically.",
                },
                "query_params": {
                    "type": "object",
                    "description": 'Optional query parameters e.g. {"expand": "names", "fields": "summary,status"}',
                    "default": {},
                },
            },
            "required": ["path"],
        },
    },
    {
        "name": "jira_mutate",
        "description": (
            "Disabled safety placeholder. Raw Jira writes are never available to the model because "
            "they bypass target resolution, user approval, and read-back verification."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "method": {
                    "type": "string",
                    "enum": ["POST", "PUT", "PATCH", "DELETE"],
                    "description": "HTTP method",
                },
                "path": {
                    "type": "string",
                    "description": "API path â€” just the endpoint, e.g. 'issue/ROCM-123'. Do NOT include /rest/api/2/ or /rest/api/3/ â€” those are added automatically.",
                },
                "body": {
                    "type": "object",
                    "description": "Request body as a JSON object",
                    "default": {},
                },
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
    "jira_mutate": "🛡️ Blocking unverified Jira mutation...",
}


# â”€â”€ Handler implementations â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€


def _sanitize_jql(jql: str) -> str:
    """Quote unquoted multi-word string values in JQL.

    LLMs frequently emit `project = Blue Ocean` instead of `project = "Blue Ocean"`.
    Jira's parser treats the second word as a stray token and raises a parse error.
    This wraps unquoted multi-word values that follow = or != in double quotes.
    """

    def _quote(m: re.Match) -> str:
        op, val, tail = m.group(1), m.group(2).strip(), m.group(3)
        # Skip already-quoted values, numbers, function calls (contain parens), single words
        if val.startswith(('"', "'")) or "(" in val or " " not in val:
            return m.group(0)
        return f'{op}"{val}"{tail}'

    # Match: (= or !=) <unquoted value not containing quotes/parens> (AND|OR|ORDER|end)
    return re.sub(
        r'([!=]=?\s+)([^"\'()\n,\[\]]+?)(\s+(?:AND|OR|ORDER\s+BY)\b|\s*$)',
        _quote,
        jql,
        flags=re.IGNORECASE,
    )


def _jira_search_post(
    jql: str, max_results: int = 20, fields: list | None = None
) -> dict:
    """POST /search/jql on Cloud (v3); falls back to POST /search on Server (v2)."""
    if fields is None:
        fields = ["summary", "status", "priority"]
    jql = _sanitize_jql(jql)
    max_results = max(1, max_results)  # Jira rejects maxResults < 1
    if jira_is_cloud():
        return jira_api(
            "POST",
            "search/jql",
            {"jql": jql, "maxResults": max_results, "fields": fields},
        )
    else:
        return jira_api(
            "POST", "search", {"jql": jql, "maxResults": max_results, "fields": fields}
        )


def _tool_list_jira_issues(max_results: int = 10) -> dict:
    try:
        data = _jira_search_post(
            "assignee = currentUser() ORDER BY updated DESC", max_results=max_results
        )
        return {
            "issues": [
                {
                    "key": i["key"],
                    "summary": i["fields"].get("summary", ""),
                    "status": i["fields"].get("status", {}).get("name", ""),
                    "priority": (i["fields"].get("priority") or {}).get("name", ""),
                    "url": f"{jira_browse_url()}/browse/{i['key']}",
                }
                for i in data.get("issues", [])
            ]
        }
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
    if node_type in (
        "paragraph",
        "heading",
        "bulletList",
        "orderedList",
        "blockquote",
        "codeBlock",
        "rule",
    ):
        return joined.strip() + "\n"
    if node_type == "listItem":
        return "â€¢ " + joined.strip() + "\n"
    if node_type == "hardBreak":
        return "\n"
    return joined


def _tool_jira_get_issue(issue_key: str, _context_id: str = "") -> dict:
    from .mutations import rovo_jira_call
    try:
        issue_key = _extract_issue_key(issue_key)
        target = resolve_target_for_context(issue_key, _context_id)
    except JiraTargetResolutionError as exc:
        return _target_resolution_result(exc, _context_id)
    if target.adapter == "rovo-mcp":
        try:
            raw = rovo_jira_call(target, "get_issue", {"issueIdOrKey": issue_key})
            rdata = raw.get("data", raw) if isinstance(raw, dict) else {}
            f = rdata.get("fields", {}) if isinstance(rdata, dict) else {}
            return {
                "key": rdata.get("key", issue_key),
                "summary": f.get("summary", ""),
                "status": (f.get("status") or {}).get("name", ""),
                "priority": (f.get("priority") or {}).get("name", ""),
                "assignee": (f.get("assignee") or {}).get("displayName", "Unassigned"),
                "reporter": (f.get("reporter") or {}).get("displayName", ""),
                "type": (f.get("issuetype") or {}).get("name", ""),
                "description": str(f.get("description") or "")[:2000],
                "url": target.issue_url(issue_key),
            }
        except JiraTargetResolutionError as exc:
            return _target_resolution_result(exc, _context_id)
        except Exception as exc:
            return {"error": str(exc)}
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
        comments.append(
            {
                "author": (c.get("author") or {}).get("displayName", ""),
                "created": (c.get("created") or "")[:10],
                "body": body,
            }
        )
    # Collect non-null custom fields with human-readable names
    custom_fields: dict = {}
    for field_id, value in f.items():
        if (
            not field_id.startswith("customfield_")
            or value is None
            or value == []
            or value == ""
        ):
            continue
        label = field_names.get(field_id, field_id)
        if isinstance(value, dict):
            display = (
                value.get("value")
                or value.get("name")
                or value.get("displayName")
                or str(value)
            )
        elif isinstance(value, list):
            display = [
                (v.get("value") or v.get("name") or v.get("displayName") or str(v))
                if isinstance(v, dict)
                else str(v)
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


def _tool_jira_search(jql: str, max_results: int = 20, _context_id: str = "") -> dict:
    from .mutations import rovo_jira_call
    try:
        target = resolve_target_for_context(context_id=_context_id)
    except JiraTargetResolutionError as exc:
        return _target_resolution_result(exc, _context_id)
    if target.adapter == "rovo-mcp":
        # Rovo does not expose a JQL search endpoint in the verified allowlist.
        # Fall through to the direct path which will fail with a clear auth error
        # rather than silently passing the JQL string as an issue key to getJiraIssue.
        return {"error": f"JQL search is not supported for the Rovo-connected Jira site ({target.base_url}). Provide the full issue URL or use jira_get_issue with a specific issue key.", "site": target.base_url}
    data = _jira_search_post(
        jql,
        max_results=max_results,
        fields=["summary", "status", "priority", "assignee"],
    )
    return {
        "total": data.get("total", 0),
        "issues": [
            {
                "key": i["key"],
                "summary": i["fields"].get("summary", ""),
                "status": i["fields"].get("status", {}).get("name", ""),
                "priority": (i["fields"].get("priority") or {}).get("name", ""),
                "assignee": (i["fields"].get("assignee") or {}).get(
                    "displayName", "Unassigned"
                ),
                "url": f"{jira_browse_url()}/browse/{i['key']}",
            }
            for i in data.get("issues", [])
        ],
    }


def _tool_jira_get_project_meta(project: str) -> dict:
    data = jira_api(
        "GET",
        f"issue/createmeta?projectKeys={project}&expand=projects.issuetypes.fields",
    )
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
                    vid = v.get("id") or v.get("value") or ""
                    vname = v.get("name") or v.get("value") or ""
                    if vname:
                        allowed_values.append({"id": vid, "name": vname})
                required_fields.append(
                    {
                        "key": fname,
                        "name": fdata.get("name", fname),
                        "type": schema.get("type", ""),
                        "system": schema.get("system", fname),
                        "required": bool(fdata.get("required")),
                        "allowed": allowed_values,
                    }
                )
        issue_types.append(
            {
                "name": it.get("name", ""),
                "id": it.get("id", ""),
                "subtask": it.get("subtask", False),
                "required_fields": required_fields,
            }
        )
    return {"project": project, "issue_types": issue_types}


def _tool_jira_create_issue(
    project: str,
    summary: str,
    issue_type: str,
    description: str = "",
    priority: str = "",
    extra_fields: str = "",
) -> dict:
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
        results = jira_api(
            "GET",
            f"user/search?query={urllib.parse.quote(query)}&maxResults=5",
            api_version="3",
        )
        return {
            "users": [
                {
                    "display_name": u.get("displayName", ""),
                    "account_id": u.get("accountId", ""),
                    "email": u.get("emailAddress", ""),
                    "mention_id": u.get("accountId", ""),
                    "mention_hint": f"Use accountId '{u.get('accountId', '')}' in comment",
                }
                for u in (results if isinstance(results, list) else [])
            ]
        }
    else:
        # Server: /rest/api/2/user/search returns username / name
        results = jira_api(
            "GET", f"user/search?username={urllib.parse.quote(query)}&maxResults=5"
        )
        return {
            "users": [
                {
                    "display_name": u.get("displayName", ""),
                    "username": u.get("name", ""),
                    "email": u.get("emailAddress", ""),
                    "mention_id": u.get("name", ""),
                    "mention_hint": f"Use @{u.get('name', '')} in comment",
                }
                for u in (results if isinstance(results, list) else [])
            ]
        }


def _build_adf_comment(text: str) -> dict:
    """Convert plain text with @accountId or [~accountid:...] tokens to ADF.

    Accepts two mention formats so the LLM can use either:
      @712020:abc-123-def   (preferred)
      [~accountid:712020:abc-123-def]  (wiki markup â€” also accepted)
    Both are converted to ADF mention nodes so Jira sends real notifications.
    Multi-line text is preserved as separate paragraph nodes.
    """
    _MENTION_RE = re.compile(
        r"@([A-Za-z0-9:\-_.]+)"  # @accountId
        r"|\[~accountid:([A-Za-z0-9:\-_.]+)\]",  # [~accountid:...] wiki markup
        re.IGNORECASE,
    )

    def _para(line: str) -> dict:
        inline_nodes = []
        pos = 0
        for m in _MENTION_RE.finditer(line):
            if m.start() > pos:
                inline_nodes.append({"type": "text", "text": line[pos : m.start()]})
            account_id = m.group(1) or m.group(2)
            inline_nodes.append(
                {
                    "type": "mention",
                    "attrs": {"id": account_id, "text": f"@{account_id}"},
                }
            )
            pos = m.end()
        if pos < len(line):
            inline_nodes.append({"type": "text", "text": line[pos:]})
        return {
            "type": "paragraph",
            "content": inline_nodes or [{"type": "text", "text": ""}],
        }

    paragraphs = [_para(line) for line in text.split("\n")]
    return {"version": 1, "type": "doc", "content": paragraphs}


# Jira Cloud (API v3) requires rich-text fields like `description` to be ADF
# objects, not plain strings â€” sending a string yields HTTP 400
# "Operation value must be an Atlassian Document". The comment ADF builder is
# general (mention-aware, multi-line) and works for descriptions too.
_build_adf_doc = _build_adf_comment


def _tool_jira_add_comment(issue_key: str, comment: str, _context_id: str = "") -> dict:
    """Stage a comment; approval verifies its returned ID on the same issue."""
    from .mutations import rovo_jira_call
    try:
        issue_key = _extract_issue_key(issue_key)
        target = resolve_target_for_context(issue_key, _context_id, for_write=True)
        if _context_id:
            select_target_for_context(_context_id, target.id)
        if target.adapter == "rovo-mcp":
            rovo_jira_call(target, "get_issue", {"issueIdOrKey": issue_key})
        else:
            jira_api("GET", f"issue/{issue_key}?fields=comment")
    except JiraTargetResolutionError as exc:
        return _target_resolution_result(exc, _context_id)
    except RuntimeError as exc:
        return {"error": str(exc)}
    from skills._drafts import create_draft
    draft_id = create_draft(
        "jira-comment",
        {"issue_key": issue_key, "comment": comment, "jira_target": target.to_dict(), "context_id": _context_id},
        {"issue_key": issue_key, "comment": comment, "site": target.public_dict()},
    )
    return {"_draft": "jira-comment", "data": {"draft_id": draft_id, "issue_key": issue_key, "comment": comment, "jira_site": target.public_dict()}, "_user_message": "Jira comment is ready for review."}


def _tool_jira_update_issue(
    issue_key: str,
    summary: str = "",
    priority: str = "",
    assignee: str = "",
    reporter: str = "",
    parent_key: str = "",
    labels: str = "",
    description: str = "",
    components: str = "",
    issue_type: str = "",
    extra_fields: str = "",
    _context_id: str = "",
) -> dict:
    """Read/validate and stage an update; approval performs the only write."""
    from .mutations import rovo_jira_call
    try:
        issue_key = _extract_issue_key(issue_key)
        target = resolve_target_for_context(issue_key, _context_id, for_write=True)
        if _context_id:
            select_target_for_context(_context_id, target.id)
    except JiraTargetResolutionError as exc:
        return _target_resolution_result(exc, _context_id)
    fields: dict = {}
    if issue_type:
        if target.adapter == "rovo-mcp":
            # Rovo does not expose editmeta; skip the guard and let Rovo validate server-side.
            pass
        else:
            # Check editmeta first â€” if issuetype is not an editable field on this issue,
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
                            f"This is a Jira screen/workflow configuration restriction â€” "
                            f"use the UI Move wizard or recreate the ticket as the target type."
                        )
                    }
            except Exception as e:
                return {
                    "error": (
                        f"Could not check editmeta for {issue_key} before attempting issue type change: {e}. "
                        f"Aborting to avoid a known-failing update. "
                        f"Call jira_get('issue/{issue_key}/editmeta') directly to diagnose."
                    )
                }
        # Use id if numeric (from project meta), name otherwise
        fields["issuetype"] = (
            {"id": issue_type} if issue_type.isdigit() else {"name": issue_type}
        )
    if summary:
        fields["summary"] = summary
    if priority:
        fields["priority"] = {"name": priority}
    if assignee:
        if target.is_cloud:
            fields["assignee"] = {"accountId": assignee}
        else:
            fields["assignee"] = {"name": assignee}
    if reporter:
        fields["reporter"] = {"accountId": reporter} if target.is_cloud else {"name": reporter}
    if parent_key:
        fields["parent"] = {"key": parent_key}
    if labels:
        new_labels = [l.strip() for l in labels.split(",") if l.strip()]
        # Prefix with + to append, - to remove, or plain to replace
        if all(l.startswith("+") for l in new_labels):
            # Append mode: merge with existing labels (direct only; Rovo sends as-is)
            if target.adapter != "rovo-mcp":
                try:
                    current = jira_api("GET", f"issue/{issue_key}?fields=labels")
                    existing = current.get("fields", {}).get("labels", [])
                    merged = list(set(existing + [l.lstrip("+") for l in new_labels]))
                    fields["labels"] = merged
                except Exception:
                    fields["labels"] = [l.lstrip("+") for l in new_labels]
            else:
                fields["labels"] = [l.lstrip("+") for l in new_labels]
        elif all(l.startswith("-") for l in new_labels):
            # Remove mode: remove from existing labels (direct only; Rovo sends as-is)
            if target.adapter != "rovo-mcp":
                try:
                    current = jira_api("GET", f"issue/{issue_key}?fields=labels")
                    existing = current.get("fields", {}).get("labels", [])
                    to_remove = {l.lstrip("-") for l in new_labels}
                    fields["labels"] = [l for l in existing if l not in to_remove]
                except Exception:
                    fields["labels"] = []
            else:
                fields["labels"] = [l.lstrip("-") for l in new_labels]
        else:
            # Replace mode
            fields["labels"] = [l.lstrip("+") for l in new_labels]
    if description:
        fields["description"] = (
            _build_adf_doc(description) if target.is_cloud else description
        )
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
        return {
            "error": "No fields to update â€” at least one of: summary, description, priority, assignee, reporter, parent_key, labels, components, issue_type, or extra_fields must be provided.",
            "hint": "To update the description, call jira_update_issue with issue_key and description='your text'.",
        }
    # Capture current state before approval. Confirms the issue exists on
    # the selected site. For Rovo targets use rovo_jira_call; for direct
    # targets use jira_api so no Rovo credential is used.
    try:
        if target.adapter == "rovo-mcp":
            rovo_jira_call(target, "get_issue", {"issueIdOrKey": issue_key})
        else:
            jira_api("GET", f"issue/{issue_key}?fields=*all")
    except Exception as exc:
        return {"error": f"Could not validate {issue_key} on the selected Jira site: {exc}"}

    from skills._drafts import create_draft
    draft_id = create_draft(
        "jira-update",
        {"issue_key": issue_key, "fields": fields, "jira_target": target.to_dict(), "context_id": _context_id},
        {"issue_key": issue_key, "fields": fields, "site": target.public_dict()},
    )
    return {
        "_draft": "jira-update",
        "data": {"draft_id": draft_id, "issue_key": issue_key, "fields": fields, "jira_site": target.public_dict()},
        "_user_message": "Jira update is ready for review. Approve it to apply and verify the selected site.",
    }


def _tool_jira_add_watcher(
    issue_key: str, account_id: str, display_name: str = "", _context_id: str = "",
) -> dict:
    """Stage an exact-account watcher mutation for HITL approval."""
    try:
        issue_key = _extract_issue_key(issue_key)
        target = resolve_target_for_context(issue_key, _context_id, for_write=True)
        if _context_id:
            select_target_for_context(_context_id, target.id)
    except JiraTargetResolutionError as exc:
        return _target_resolution_result(exc, _context_id)
    if target.adapter == "rovo-mcp":
        return {
            "error": "Watcher management is not available for Rovo-connected Jira sites. "
                     "Open the issue in your browser to add watchers directly.",
            "unavailable": True,
        }
    try:
        jira_api("GET", f"issue/{issue_key}?fields=watcher")
    except RuntimeError as exc:
        return {"error": str(exc)}
    from skills._drafts import create_draft
    draft_id = create_draft(
        "jira-watcher",
        {"issue_key": issue_key, "account_id": account_id, "jira_target": target.to_dict(), "context_id": _context_id},
        {"issue_key": issue_key, "account_id": account_id, "site": target.public_dict()},
    )
    return {
        "_draft": "jira-watcher",
        "data": {"draft_id": draft_id, "issue_key": issue_key, "watcher": display_name or account_id, "jira_site": target.public_dict()},
        "_user_message": "Watcher change is ready for review. Approve it to apply and verify the selected site.",
    }


def _tool_jira_stage_attachment(issue_key: str, upload_id: str, _context_id: str = "") -> dict:
    """Stage an immutable attachment snapshot for approval, never a model path."""
    from .mutations import staged_attachment
    try:
        issue_key = _extract_issue_key(issue_key)
        target = resolve_target_for_context(issue_key, _context_id, for_write=True)
        if _context_id:
            select_target_for_context(_context_id, target.id)
    except JiraTargetResolutionError as exc:
        return _target_resolution_result(exc, _context_id)
    if target.adapter == "rovo-mcp":
        return {
            "error": "File attachment is not available for Rovo-connected Jira sites. "
                     "Open the issue in your browser to attach files directly.",
            "unavailable": True,
        }
    try:
        attachment = staged_attachment(upload_id)
        jira_api("GET", f"issue/{issue_key}?fields=attachment")
    except JiraTargetResolutionError as exc:
        return _target_resolution_result(exc, _context_id)
    except RuntimeError as exc:
        return {"error": str(exc)}
    from skills._drafts import create_draft
    draft_id = create_draft(
        "jira-attachment",
        {"issue_key": issue_key, "upload_id": attachment["upload_id"], "jira_target": target.to_dict(), "context_id": _context_id},
        {"issue_key": issue_key, "attachment": {key: attachment[key] for key in ("filename", "size", "sha256")}},
    )
    return {
        "_draft": "jira-attachment",
        "data": {"draft_id": draft_id, "issue_key": issue_key, "filename": attachment["filename"], "size": attachment["size"], "sha256": attachment["sha256"], "jira_site": target.public_dict()},
        "_user_message": "Jira attachment is ready for review. Approve it to upload the verified staged copy.",
    }


def _tool_jira_stage_teams_attachment(
    issue_key: str, chat_id: str, message_id: str, _context_id: str = "",
) -> dict:
    """Bridge one trusted Teams *file* attachment into the Jira HITL flow.

    The Teams resolver only accepts the message identity obtained from a
    selected/pinned chat context. It resolves SharePoint/OneDrive metadata;
    the bytes are immediately transformed into a private opaque Jira snapshot
    and no local filename/path is returned to the model.
    """
    try:
        issue_key = _extract_issue_key(issue_key)
        target = resolve_target_for_context(issue_key, _context_id, for_write=True)
        if _context_id:
            select_target_for_context(_context_id, target.id)
    except JiraTargetResolutionError as exc:
        return _target_resolution_result(exc, _context_id)
    if target.adapter == "rovo-mcp":
        return {
            "error": "File attachment is not available for Rovo-connected Jira sites. "
                     "Open the issue in your browser to attach files directly.",
            "unavailable": True,
        }
    try:
        from skills.onedrive.tools import _tool_resolve_teams_attachment, download_drive_item_bytes
        from .mutations import stage_attachment
        resolved = _tool_resolve_teams_attachment(chat_id, message_id)
        if resolved.get("error"):
            return {"error": resolved["error"]}
        # A multi-file Teams message must be narrowed by an explicit UI choice
        # in a follow-up; choosing the first silently would be surprising.
        if isinstance(resolved.get("attachments"), list):
            return {"error": "This Teams message has multiple files. Select one attachment in Teams and try again."}
        file_id = str(resolved.get("item_id") or "")
        drive_id = str(resolved.get("drive_id") or "")
        downloaded = download_drive_item_bytes(file_id, drive_id)
        if downloaded.get("error"):
            return {"error": downloaded["error"]}
        staged = stage_attachment(
            downloaded["filename"], downloaded["content"], downloaded["content_type"],
        )
    except Exception as exc:
        return {"error": f"Could not stage the Teams attachment: {exc}"}
    # Reuse the single attachment verifier/draft contract rather than creating
    # a special mutation route for Teams-originated bytes.
    return _tool_jira_stage_attachment(issue_key, staged["upload_id"], _context_id)


def _tool_jira_stage_teams_image(
    issue_key: str, image_url: str, filename: str = "", _context_id: str = "",
) -> dict:
    """Fetch an authenticated inline Teams image into Jira's opaque staging area."""
    try:
        issue_key = _extract_issue_key(issue_key)
        target = resolve_target_for_context(issue_key, _context_id, for_write=True)
        if _context_id:
            select_target_for_context(_context_id, target.id)
    except JiraTargetResolutionError as exc:
        return _target_resolution_result(exc, _context_id)
    if target.adapter == "rovo-mcp":
        return {
            "error": "File attachment is not available for Rovo-connected Jira sites. "
                     "Open the issue in your browser to attach files directly.",
            "unavailable": True,
        }
    parsed = urlparse((image_url or "").strip())
    host = parsed.hostname.lower() if parsed.hostname else ""
    if parsed.scheme != "https" or not any(host == item or host.endswith("." + item) for item in _TEAMS_IMAGE_HOSTS):
        return {"error": "The image must be an https Teams-hosted image from the selected Teams message."}
    try:
        import httpx
        from routes.teams import _get_skype_module
        headers: dict[str, str] = {}
        try:
            token, _ = _get_skype_module().get_auth()
        except Exception:
            token = ""
        if token:
            headers["Authorization" if "asm.skype.com" in host else "X-Skypetoken"] = (
                f"skype_token {token}" if "asm.skype.com" in host else token
            )
        else:
            from skills._m365.helpers import make_teams_gc
            headers["Authorization"] = f"Bearer {make_teams_gc().get_token()}"
        with httpx.Client(timeout=httpx.Timeout(30.0), follow_redirects=False) as client:
            with client.stream("GET", image_url, headers=headers) as response:
                response.raise_for_status()
                declared = int(response.headers.get("content-length") or 0)
                if declared > _MAX_JIRA_ATTACHMENT_BYTES:
                    return {"error": "The Teams image exceeds Jira's 20 MB attachment limit."}
                chunks: list[bytes] = []
                total = 0
                for chunk in response.iter_bytes():
                    total += len(chunk)
                    if total > _MAX_JIRA_ATTACHMENT_BYTES:
                        return {"error": "The Teams image exceeds Jira's 20 MB attachment limit."}
                    chunks.append(chunk)
                content = b"".join(chunks)
                content_type = response.headers.get("content-type", "image/png").split(";", 1)[0]
        if not content.startswith((b"\x89PNG", b"\xff\xd8\xff", b"GIF8", b"RIFF")):
            return {"error": "Teams did not return a supported image. Reopen the Teams message and try again."}
        from .mutations import stage_attachment
        ext = {"image/png": "png", "image/jpeg": "jpg", "image/gif": "gif", "image/webp": "webp"}.get(content_type, "png")
        staged = stage_attachment(filename or f"teams-image.{ext}", content, content_type)
    except Exception as exc:
        return {"error": f"Could not fetch the Teams image for Jira staging: {exc}"}
    return _tool_jira_stage_attachment(issue_key, staged["upload_id"], _context_id)


def _tool_jira_transition(
    issue_key: str, transition_name: str, comment: str = "", _context_id: str = ""
) -> dict:
    from .mutations import rovo_jira_call
    try:
        issue_key = _extract_issue_key(issue_key)
        target = resolve_target_for_context(issue_key, _context_id, for_write=True)
        if _context_id:
            select_target_for_context(_context_id, target.id)
    except JiraTargetResolutionError as exc:
        return _target_resolution_result(exc, _context_id)

    if target.adapter == "rovo-mcp":
        # Rovo's transitionJiraIssue requires a non-empty transition ID.
        # The Rovo MCP schema does not expose a transitions-list endpoint, so
        # there is no way to map a name to an ID without direct credentials.
        # Refuse explicitly rather than staging a draft that will fail at approval.
        return {
            "error": (
                "Issue transitions are not available for Rovo-connected Jira sites because "
                "Rovo does not expose a transition-list API. "
                "Open the issue in your browser to change its status directly."
            ),
            "unavailable": True,
        }

    # Direct path: expand fields so we can detect required fields (like resolution)
    try:
        transitions = jira_api(
            "GET", f"issue/{issue_key}/transitions?expand=transitions.fields"
        )
    except RuntimeError as exc:
        return {"error": str(exc)}
    match = None
    for t in transitions.get("transitions", []):
        if t.get("name", "").lower() == transition_name.lower():
            match = t
            break
    if not match:
        avail = [t.get("name") for t in transitions.get("transitions", [])]
        return {
            "error": f"Transition '{transition_name}' not found. Available: {avail}"
        }
    payload = {"transition": {"id": str(match["id"])}}
    # Auto-fill required transition fields (e.g., resolution for "Done")
    fields = match.get("fields", {})
    if fields:
        payload_fields = {}
        for fname, fdata in fields.items():
            if fdata.get("required"):
                allowed = fdata.get("allowedValues", [])
                if allowed:
                    payload_fields[fname] = {
                        "name": allowed[0].get("name", allowed[0].get("value", ""))
                    }
        if payload_fields:
            payload["fields"] = payload_fields
    if comment:
        payload["update"] = {"comment": [{"add": {"body": comment}}]}
    from skills._drafts import create_draft
    draft_id = create_draft(
        "jira-transition",
        {"issue_key": issue_key, "transition_name": transition_name, "expected_status": (match.get("to") or {}).get("name", ""), "payload": payload, "jira_target": target.to_dict(), "context_id": _context_id},
        {"issue_key": issue_key, "transition_name": transition_name, "site": target.public_dict()},
    )
    return {"_draft": "jira-transition", "data": {"draft_id": draft_id, "issue_key": issue_key, "transition_name": transition_name, "jira_site": target.public_dict()}, "_user_message": "Jira transition is ready for review."}


def _tool_jira_link_issues(
    issue_key: str, other_key: str, link_type: str = "Relates", _context_id: str = ""
) -> dict:
    from .mutations import rovo_jira_call
    try:
        issue_key = _extract_issue_key(issue_key)
        target = resolve_target_for_context(issue_key, _context_id, for_write=True)
        if _context_id:
            select_target_for_context(_context_id, target.id)
        if target.adapter == "rovo-mcp":
            raw = rovo_jira_call(target, "get_issue", {"issueIdOrKey": issue_key})
            before_obj = raw.get("data", raw) if isinstance(raw, dict) else {}
            before = before_obj if isinstance(before_obj, dict) else {}
        else:
            before = jira_api("GET", f"issue/{issue_key}?fields=issuelinks")
            jira_api("GET", f"issue/{other_key}?fields=summary")
    except JiraTargetResolutionError as exc:
        return _target_resolution_result(exc, _context_id)
    except RuntimeError as exc:
        return {"error": str(exc)}
    from skills._drafts import create_draft
    payload = {"type": {"name": link_type}, "inwardIssue": {"key": other_key}, "outwardIssue": {"key": issue_key}}
    before_ids = [str(item.get("id", "")) for item in ((before.get("fields") or {}).get("issuelinks") or []) if isinstance(item, dict)]
    draft_id = create_draft("jira-link", {"issue_key": issue_key, "other_key": other_key, "link_type": link_type, "before_link_ids": before_ids, "payload": payload, "jira_target": target.to_dict(), "context_id": _context_id}, {"issue_key": issue_key, "other_key": other_key, "link_type": link_type})
    return {"_draft": "jira-link", "data": {"draft_id": draft_id, "issue_key": issue_key, "other_key": other_key, "link_type": link_type, "jira_site": target.public_dict()}, "_user_message": "Jira issue link is ready for review."}


def _tool_jira_get_issue_links(issue_key: str) -> dict:
    issue = jira_api("GET", f"issue/{issue_key}?fields=issuelinks")
    links = issue.get("fields", {}).get("issuelinks", [])
    result = []
    for lnk in links:
        link_type = lnk.get("type", {}).get("name", "")
        if "outwardIssue" in lnk:
            result.append(
                {
                    "type": link_type,
                    "direction": "outward",
                    "link_id": str(lnk.get("id", "")),
                    "key": lnk["outwardIssue"]["key"],
                    "summary": lnk["outwardIssue"].get("fields", {}).get("summary", ""),
                }
            )
        elif "inwardIssue" in lnk:
            result.append(
                {
                    "type": link_type,
                    "direction": "inward",
                    "link_id": str(lnk.get("id", "")),
                    "key": lnk["inwardIssue"]["key"],
                    "summary": lnk["inwardIssue"].get("fields", {}).get("summary", ""),
                }
            )
    return {"issue_key": issue_key, "links": result}


def _tool_jira_add_remote_link(issue_key: str, url: str, title: str) -> dict:
    return {"error": "Direct Jira remote-link creation is disabled until the link draft workflow can verify the created link on the selected site."}


def _tool_jira_get_epic_children(epic_key: str, max_results: int = 50) -> dict:
    data = _jira_search_post(
        f'"Epic Link" = {epic_key} ORDER BY status ASC, priority DESC',
        max_results=max_results,
        fields=["summary", "status", "priority", "assignee", "issuetype"],
    )
    browse = jira_browse_url()
    return {
        "epic": epic_key,
        "children": [
            {
                "key": i["key"],
                "type": i["fields"].get("issuetype", {}).get("name", ""),
                "summary": i["fields"].get("summary", ""),
                "status": i["fields"].get("status", {}).get("name", ""),
                "priority": (i["fields"].get("priority") or {}).get("name", ""),
                "assignee": (i["fields"].get("assignee") or {}).get(
                    "displayName", "Unassigned"
                ),
                "url": f"{browse}/browse/{i['key']}",
            }
            for i in data.get("issues", [])
        ],
        "total": data.get("total", 0),
    }


def _tool_jira_unlink_issues(link_id: str) -> dict:
    return {"error": "Direct Jira unlinking is disabled until the link draft workflow can verify the removed link on the selected site."}


def _tool_jira_list_link_types() -> dict:
    data = jira_api("GET", "issueLinkType")
    return {
        "link_types": [
            {
                "name": lt.get("name", ""),
                "inward": lt.get("inward", ""),
                "outward": lt.get("outward", ""),
            }
            for lt in data.get("issueLinkTypes", [])
        ]
    }


def _tool_jira_list_fields(query: str = "") -> dict:
    """List all fields in the Jira instance, optionally filtered by name."""
    data = jira_api("GET", "field")
    fields_list = data if isinstance(data, list) else []
    if query:
        q = query.lower()
        fields_list = [f for f in fields_list if q in (f.get("name", "") or "").lower()]
    return {
        "fields": [
            {
                "id": f.get("id", ""),
                "name": f.get("name", ""),
                "custom": f.get("custom", False),
                "schema_type": (f.get("schema") or {}).get("type", ""),
            }
            for f in fields_list[:50]  # Cap at 50 to avoid overwhelming context
        ]
    }


def _tool_jira_open_create_form(
    project: str,
    summary: str = "",
    issue_type: str = "",
    description: str = "",
    priority: str = "",
    extra_fields: str = "",
    parent_key: str = "",
    assignee_account_id: str = "",
    assignee_display: str = "",
    _context_id: str = "",
) -> dict:
    """Stage a Jira issue for user review via a draft approval card.

    Resolves the parent summary for display, stores all fields in
    _pending_drafts, and returns a _draft signal so the frontend renders
    a structured review card. The actual Jira API call happens in
    approve_draft (routes/drafts.py) after the user clicks Create issue.
    Dispatches by adapter: direct targets use the REST API for pre-reads;
    Rovo targets use rovo_jira_call. The approval path handles both.
    """
    from skills._drafts import create_draft
    from .mutations import rovo_jira_call

    # Capture the exact Jira site before any read used to populate the card.
    # Approval validates this target again, so a later config change can never
    # redirect a reviewed draft to another Jira instance.
    try:
        target = resolve_target_for_context(context_id=_context_id)
        if _context_id:
            select_target_for_context(_context_id, target.id)
    except JiraTargetResolutionError as exc:
        return _target_resolution_result(exc, _context_id)

    # Parse extra_fields
    parsed_extra: dict = {}
    if extra_fields:
        try:
            parsed_extra = (
                json.loads(extra_fields)
                if isinstance(extra_fields, str)
                else extra_fields
            )
        except Exception:
            pass

    # Resolve parent summary for display on the draft card
    parent_summary = ""
    if parent_key and target.adapter == "builtin-rest":
        try:
            parent_issue = jira_api("GET", f"issue/{parent_key}?fields=summary")
            parent_summary = (parent_issue.get("fields") or {}).get("summary", "")
        except Exception:
            pass

    # Validate project and issue type exist on the selected site before staging.
    # For direct targets: use the existing REST meta path.
    # For Rovo targets: use allowlisted Rovo operations so no direct credential is touched.
    unfilled_fields: list = []
    if target.adapter == "rovo-mcp":
        try:
            # getVisibleJiraProjects: cloudId injected by rovo_jira_call.
            # expandIssueTypes defaults to true, so project objects embed issueTypes.
            # Use searchString to narrow to the requested project key.
            projects_raw = rovo_jira_call(target, "get_projects", {"searchString": project})
            def _unwrap(raw):
                """Unwrap a list from a Rovo MCP response."""
                if isinstance(raw, list):
                    return raw
                if isinstance(raw, dict):
                    for k in ("values", "projects", "data"):
                        v = raw.get(k)
                        if isinstance(v, list):
                            return v
                return []
            project_list = _unwrap(projects_raw)
            project_keys = {str(p.get("key", "")).upper() for p in project_list if isinstance(p, dict)}
            if project_keys and project.upper() not in project_keys:
                return {"error": f"Project '{project}' was not found on the selected Rovo Jira site. Available: {sorted(project_keys)[:10]}"}
        except Exception as exc:
            return {"error": f"Could not verify project '{project}' on the selected Rovo Jira site: {exc}"}
        if issue_type:
            try:
                # getJiraProjectIssueTypesMetadata: cloudId injected; projectIdOrKey required.
                types_raw = rovo_jira_call(target, "get_issue_types", {"projectIdOrKey": project})
                type_list = _unwrap(types_raw)
                type_names = {str(t.get("name", "")).lower() for t in type_list if isinstance(t, dict)}
                if type_names and issue_type.lower() not in type_names:
                    return {"error": f"Issue type '{issue_type}' is not available for project '{project}' on the selected Rovo Jira site. Available: {sorted(type_names)[:10]}"}
            except Exception as exc:
                return {"error": f"Could not verify issue type '{issue_type}' for project '{project}' on the selected Rovo Jira site: {exc}"}
    else:
        try:
            meta = _tool_jira_get_project_meta(project)
            for it in meta.get("issue_types", []):
                if issue_type and it["name"].lower() != issue_type.lower():
                    continue
                for f in it.get("required_fields", []):
                    if not f.get("required"):
                        continue
                    fkey = f["key"]
                    if fkey == "priority" and priority:
                        continue
                    if fkey == "assignee" and assignee_account_id:
                        continue
                    if fkey in ("parent", "customfield_10014") and parent_key:
                        continue
                    if fkey in parsed_extra:
                        continue
                    unfilled_fields.append({
                        "key": fkey,
                        "name": f["name"],
                        "type": f.get("type", "string"),
                        "allowed_values": [v["name"] for v in f.get("allowed", [])[:10]],
                    })
                break
        except Exception:
            pass

    is_cloud = target.is_cloud

    draft_id = create_draft(
        "jira-create",
        {
            "project": project,
            "summary": summary,
            "issue_type": issue_type,
            "description": description,
            "priority": priority,
            "extra_fields": parsed_extra,
            "parent_key": parent_key,
            "assignee_account_id": assignee_account_id,
            "is_cloud": is_cloud,
            "jira_target": target.to_dict(),
            "context_id": _context_id,
        },
        {"summary": summary, "project": project},
    )

    result: dict = {
        "_draft": "jira-create",
        "data": {
            "draft_id": draft_id,
            "project": project,
            "summary": summary,
            "issue_type": issue_type,
            "description": description,
            "priority": priority,
            "parent_key": parent_key,
            "parent_summary": parent_summary,
            "assignee_account_id": assignee_account_id,
            "assignee_display": assignee_display,
            "jira_site": target.public_dict(),
        },
        "_user_message": (
            "The draft card is ready above â€” review the fields and click **Create issue** to submit, "
            "or tell me here to make changes."
        ),
    }
    if unfilled_fields:
        result["unfilled_required_fields"] = unfilled_fields
        result["_user_message"] = (
            f"There are {len(unfilled_fields)} required field(s) still missing. "
            "Please provide the values listed below before I open the draft."
        )
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

        parsed = (
            _up.urlparse("?" + full_path.split("?", 1)[-1])
            if "?" in full_path
            else _up.urlparse("")
        )
        params = dict(_up.parse_qsl(parsed.query))
        jql = params.get("jql", "")
        max_results = max(1, int(params.get("maxResults", 50) or 50))
        fields_str = params.get("fields", "")
        fields = [f.strip() for f in fields_str.split(",")] if fields_str else None
        try:
            return jira_api(
                "POST",
                "search/jql",
                {
                    "jql": jql,
                    "maxResults": max_results,
                    **({"fields": fields} if fields else {}),
                },
            )
        except RuntimeError as e:
            return {"error": str(e)}
    try:
        return jira_api("GET", full_path)
    except RuntimeError as e:
        return {"error": str(e)}


def _tool_jira_mutate(method: str, path: str, body: dict | None = None) -> dict:
    """Reject unverified writes; named verified workflows must be used instead."""
    return {
        "error": (
            "Raw Jira mutation is disabled because it cannot prove the requested "
            "change persisted on the selected Jira site. Use a registered Jira "
            "draft workflow that performs read, approval, apply, and verification."
        ),
        "action": "Use jira_open_create_form for issue creation. Other verified Jira mutation forms are required for updates.",
    }


def _target_scoped(handler, reference_arg: str = ""):
    """Wrap built-in Jira reads so a multi-site key never uses global auth.

    The legacy REST client has exactly one credential set.  A target selection
    that resolves to Rovo is rejected here instead of being silently sent with
    those credentials; Rovo reads require their own adapter.
    """
    def guarded(*args, _context_id: str = "", **kwargs):
        reference = kwargs.get(reference_arg, "") if reference_arg else ""
        try:
            resolve_builtin_target(str(reference or ""), _context_id)
        except JiraTargetResolutionError as exc:
            return _target_resolution_result(exc, _context_id)
        return handler(*args, **kwargs)
    return guarded


TOOL_HANDLERS = {
    "list_jira_issues": _target_scoped(_tool_list_jira_issues),
    "jira_get_issue": _tool_jira_get_issue,
    "jira_search": _tool_jira_search,
    "jira_get_project_meta": _target_scoped(_tool_jira_get_project_meta, "project"),
    "jira_create_issue": _tool_jira_create_issue,
    "jira_search_user": _target_scoped(_tool_jira_search_user),
    "jira_add_comment": _tool_jira_add_comment,
    "jira_add_watcher": _tool_jira_add_watcher,
    "jira_stage_attachment": _tool_jira_stage_attachment,
    "jira_stage_teams_attachment": _tool_jira_stage_teams_attachment,
    "jira_stage_teams_image": _tool_jira_stage_teams_image,
    "jira_update_issue": _tool_jira_update_issue,
    "jira_transition": _tool_jira_transition,
    "jira_link_issues": _tool_jira_link_issues,
    "jira_get_issue_links": _target_scoped(_tool_jira_get_issue_links, "issue_key"),
    "jira_add_remote_link": _target_scoped(_tool_jira_add_remote_link, "issue_key"),
    "jira_get_epic_children": _target_scoped(_tool_jira_get_epic_children, "epic_key"),
    "jira_unlink_issues": _target_scoped(_tool_jira_unlink_issues),
    "jira_list_link_types": _target_scoped(_tool_jira_list_link_types),
    "jira_list_fields": _target_scoped(_tool_jira_list_fields),
    "jira_open_create_form": _tool_jira_open_create_form,
    "jira_update_form_fields": _tool_jira_update_form_fields,
    "jira_show_issues": _tool_jira_show_issues,
    "jira_get": _target_scoped(_tool_jira_get),
    "jira_mutate": _target_scoped(_tool_jira_mutate),
}
