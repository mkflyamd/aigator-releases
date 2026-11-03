"""rovo_jira_call must work against whichever Rovo tool set the connection exposes.

Rovo v1 has one named tool per action. v2 renames some, moves others behind
discover/executeRead/executeWrite, wraps responses in {"data": ...} and calls
the site id ``cloudId``. The server's own read/write hints and execute tiers
decide whether an operation may be served by a given tool.
"""

import json
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).parent.parent / "web"))

from unittest.mock import MagicMock, patch

import pytest
from skills.jira.mutations import (
    JiraTarget,
    JiraTargetResolutionError,
    _accessible_resources,
    rovo_jira_call,
)

SITE = "https://amd.atlassian.net"
CLOUD_ID = "cloud-1"


def _target():
    return JiraTarget(
        id=f"rovo:conn-1:{CLOUD_ID}", base_url=SITE, adapter="rovo-mcp", is_cloud=True,
        connection_id="conn-1", resource_id=CLOUD_ID,
    )


def _tool(name, props=(), **hints):
    tool = {"name": name, "input_schema": {"type": "object", "properties": {p: {} for p in props}}}
    if hints:
        tool["annotations"] = hints
    return tool


V2_TOOLS = [
    _tool("getAccessibleAtlassianResources"),
    _tool("getJiraIssue", ("cloudId", "issueIdOrKey", "view"), readOnlyHint=True, destructiveHint=False),
    _tool("createJiraIssue", ("cloudId", "projectKey", "summary", "issueType", "assignee", "parent"),
          readOnlyHint=False, destructiveHint=False),
    _tool("addOrEditJiraIssueComment", ("cloudId", "issueIdOrKey", "commentBody", "contentFormat"),
          readOnlyHint=False, destructiveHint=False),
    _tool("discover", ("query",), readOnlyHint=True),
    _tool("executeRead", ("cloudId", "name", "inputs"), readOnlyHint=True),
    _tool("executeWrite", ("cloudId", "name", "inputs"), readOnlyHint=False, destructiveHint=False),
]

V2_RESOURCES = json.dumps({"data": {"resources": [{"cloudId": CLOUD_ID, "url": SITE}]}})


def _discover_entry(name, tier, inputs):
    return {"name": name, "executeTool": tier, "inputs": [{"name": i} for i in inputs]}


def _client(discoverable=(), responses=None):
    """MCP client double. ``discoverable`` is a list of discover result entries."""
    client = MagicMock()
    calls = []

    def _call(tool, args):
        calls.append((tool, args))
        if tool == "getAccessibleAtlassianResources":
            return V2_RESOURCES
        if tool == "discover":
            return json.dumps({"results": list(discoverable)})
        return json.dumps((responses or {}).get(tool, {"data": {"ok": True}}))

    client.call.side_effect = _call
    client.calls = calls
    return client


def _run(operation, arguments, client, tools=V2_TOOLS):
    connection = {"id": "conn-1", "enabled": True, "cached_tools": tools}
    with patch("mcp.manager._load_connections", return_value=[connection]), \
         patch("mcp.manager._client_for", return_value=client):
        return rovo_jira_call(_target(), operation, arguments)


def _last(client, tool):
    return [args for name, args in client.calls if name == tool][-1]


def test_accessible_resources_accepts_v1_and_v2_shapes():
    v1 = _accessible_resources('{"resources": [{"id": "a", "url": "https://x.atlassian.net"}]}')
    v2 = _accessible_resources(V2_RESOURCES)
    assert [r["id"] for r in v1] == ["a"]
    assert [r["id"] for r in v2] == [CLOUD_ID]
    assert _accessible_resources('{"nope": 1}') is None


def test_renamed_comment_tool_is_used_directly():
    client = _client(responses={"addOrEditJiraIssueComment": {"data": {"id": "77"}}})
    result = _run("add_comment", {"issueIdOrKey": "ROCMAI-1", "commentBody": "hi", "contentFormat": "markdown"}, client)
    assert result == {"id": "77"}
    assert _last(client, "addOrEditJiraIssueComment")["cloudId"] == CLOUD_ID


def test_operation_behind_discover_runs_through_execute_write_with_renamed_argument():
    entry = _discover_entry("createJiraIssueLink", "executeWrite", ("cloudId", "linkType", "inwardIssue", "outwardIssue"))
    client = _client(discoverable=[entry])
    _run("create_link", {"inwardIssue": "A-1", "outwardIssue": "A-2", "type": "Blocks"}, client)
    sent = _last(client, "executeWrite")
    assert sent["name"] == "createJiraIssueLink"
    assert sent["inputs"] == {"inwardIssue": "A-1", "outwardIssue": "A-2", "linkType": "Blocks", "cloudId": CLOUD_ID}
    assert not any(name == "executeRead" for name, _ in client.calls)


def test_read_operation_behind_discover_runs_through_execute_read_and_unwraps_data():
    entry = _discover_entry("listJiraProjects", "executeRead", ("cloudId", "query"))
    client = _client(discoverable=[entry], responses={"executeRead": {"data": {"values": [{"key": "ROCMAI"}]}}})
    result = _run("get_projects", {"searchString": "ROCMAI"}, client)
    assert result == {"values": [{"key": "ROCMAI"}]}
    assert _last(client, "executeRead")["inputs"]["query"] == "ROCMAI"


def test_server_listing_a_write_under_the_read_tier_is_refused():
    entry = _discover_entry("createJiraIssueLink", "executeRead", ("cloudId",))
    client = _client(discoverable=[entry])
    with pytest.raises(JiraTargetResolutionError, match="not executeWrite"):
        _run("create_link", {"inwardIssue": "A-1", "outwardIssue": "A-2", "type": "Blocks"}, client)
    assert not any(name.startswith("execute") for name, _ in client.calls)


def test_read_operation_listed_as_destructive_is_refused():
    entry = _discover_entry("listJiraProjects", "executeDestructive", ("cloudId",))
    client = _client(discoverable=[entry])
    with pytest.raises(JiraTargetResolutionError, match="not executeRead"):
        _run("get_projects", {"searchString": "X"}, client)


def test_direct_tool_whose_hints_contradict_the_operation_is_refused():
    tools = [t for t in V2_TOOLS if t["name"] != "getJiraIssue"] + [
        _tool("getJiraIssue", ("cloudId", "issueIdOrKey"), readOnlyHint=False, destructiveHint=False)
    ]
    with pytest.raises(JiraTargetResolutionError, match="not a read operation"):
        _run("get_issue", {"issueIdOrKey": "A-1"}, _client(), tools=tools)

    destructive = [t for t in V2_TOOLS if t["name"] != "addOrEditJiraIssueComment"] + [
        _tool("addOrEditJiraIssueComment", ("cloudId",), readOnlyHint=False, destructiveHint=True)
    ]
    with pytest.raises(JiraTargetResolutionError, match="not a write operation"):
        _run("add_comment", {"issueIdOrKey": "A-1", "commentBody": "x"}, _client(), tools=destructive)


def test_connection_without_hints_is_still_served_by_name():
    tools = [_tool("getAccessibleAtlassianResources"), _tool("getJiraIssue")]
    client = _client(responses={"getJiraIssue": {"data": {"key": "A-1"}}})
    assert _run("get_issue", {"issueIdOrKey": "A-1"}, client, tools=tools) == {"key": "A-1"}


def test_unsupported_when_neither_a_tool_nor_discovery_serves_the_operation():
    tools = [_tool("getAccessibleAtlassianResources"), _tool("getJiraIssue")]
    with pytest.raises(JiraTargetResolutionError, match="does not support create link"):
        _run("create_link", {}, _client(), tools=tools)


def test_unknown_operation_name_from_discovery_is_unsupported():
    client = _client(discoverable=[_discover_entry("somethingElse", "executeWrite", ())])
    with pytest.raises(JiraTargetResolutionError, match="does not support create link"):
        _run("create_link", {"type": "Blocks"}, client)


def test_get_issue_asks_for_the_full_view_only_when_the_tool_has_one():
    client = _client()
    _run("get_issue", {"issueIdOrKey": "A-1"}, client)
    assert _last(client, "getJiraIssue")["view"] == "full"

    v1_tools = [_tool("getAccessibleAtlassianResources"), _tool("getJiraIssue", ("cloudId", "issueIdOrKey"))]
    client = _client()
    _run("get_issue", {"issueIdOrKey": "A-1"}, client, tools=v1_tools)
    assert "view" not in _last(client, "getJiraIssue")

    client = _client()
    _run("get_issue", {"issueIdOrKey": "A-1", "view": "evidence"}, client)
    assert _last(client, "getJiraIssue")["view"] == "evidence"


def test_create_issue_argument_names_follow_the_tools_own_schema():
    args = {"projectKey": "ROCMAI", "issueTypeName": "Task", "summary": "s", "assignee_account_id": "acc-1"}
    client = _client()
    _run("create_issue", dict(args), client)
    sent = _last(client, "createJiraIssue")
    assert sent["issueType"] == "Task" and sent["assignee"] == "acc-1"
    assert "issueTypeName" not in sent and "assignee_account_id" not in sent

    v1_tools = [_tool("getAccessibleAtlassianResources"),
                _tool("createJiraIssue", ("cloudId", "projectKey", "issueTypeName", "summary", "assignee_account_id"))]
    client = _client()
    _run("create_issue", dict(args), client, tools=v1_tools)
    sent = _last(client, "createJiraIssue")
    assert sent["issueTypeName"] == "Task" and sent["assignee_account_id"] == "acc-1"


def test_site_that_the_connection_cannot_access_is_still_refused():
    client = _client()
    client.call.side_effect = lambda tool, args: json.dumps(
        {"data": {"resources": [{"cloudId": "other", "url": "https://other.atlassian.net"}]}}
    ) if tool == "getAccessibleAtlassianResources" else "{}"
    with pytest.raises(JiraTargetResolutionError, match="no longer accessible"):
        _run("get_issue", {"issueIdOrKey": "A-1"}, client)


def test_discover_reply_with_plain_text_trailer_is_parsed():
    entry = _discover_entry("listJiraProjects", "executeRead", ("cloudId", "query"))
    client = _client(discoverable=[entry], responses={"executeRead": {"data": {"values": []}}})
    base = client.call.side_effect
    trailer = "\n\nalso matched (15 more) - re-run discover with a narrower query:\n  listJiraBoards"
    client.call.side_effect = lambda tool, args: base(tool, args) + (trailer if tool == "discover" else "")
    assert _run("get_projects", {"searchString": "X"}, client) == {"values": []}


def test_argument_value_the_schema_enum_rules_out_is_dropped():
    tools = [_tool("getAccessibleAtlassianResources"), {
        "name": "getJiraIssue",
        "input_schema": {"type": "object", "properties": {
            "cloudId": {}, "issueIdOrKey": {}, "view": {},
            "responseContentFormat": {"type": "string", "enum": ["markdown", "html"]},
        }},
    }]
    client = _client()
    _run("get_issue", {"issueIdOrKey": "A-1", "responseContentFormat": "adf"}, client, tools=tools)
    assert "responseContentFormat" not in _last(client, "getJiraIssue")

    client = _client()
    _run("get_issue", {"issueIdOrKey": "A-1", "responseContentFormat": "html"}, client, tools=tools)
    assert _last(client, "getJiraIssue")["responseContentFormat"] == "html"
