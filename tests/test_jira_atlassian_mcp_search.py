"""JQL search on an Atlassian MCP-connected Jira site goes through Atlassian MCP's own search tool and
comes back in the same shape as a direct-REST search."""

import json
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).parent.parent / "web"))

from unittest.mock import MagicMock, patch

import pytest
from skills.jira import tools
from skills.jira.mutations import JiraTarget, JiraTargetResolutionError, atlassian_mcp_jira_call

SITE = "https://amd.atlassian.net"
CLOUD_ID = "cloud-1"

ATLASSIAN_MCP_SITE = JiraTarget(
    id=f"atlassian-mcp:conn-1:{CLOUD_ID}", base_url=SITE, adapter="atlassian-mcp", is_cloud=True,
    connection_id="conn-1", resource_id=CLOUD_ID,
)

V2_PAGE = {
    "isLast": False,
    "nextPageToken": "abc",
    "issues": [
        {"id": "1", "key": "GFX-1", "fields": {
            "summary": "First", "status": {"name": "Open"}, "priority": {"name": "P2"},
            "assignee": {"displayName": "Maple, Jarrad"}}},
        {"id": "2", "key": "GFX-2", "fields": {"summary": "Second", "status": {"name": "Done"}}},
    ],
}


@pytest.fixture(autouse=True)
def atlassian_mcp_selected(monkeypatch):
    monkeypatch.setattr(tools, "selected_target_for_context", lambda ctx: ATLASSIAN_MCP_SITE)


def _search(jql="assignee = currentUser()", max_results=20):
    return tools._tool_jira_search(jql, max_results, "tab-atlassian-mcp-search")


def test_atlassian_mcp_site_search_uses_atlassian_mcp_and_maps_to_the_direct_shape():
    calls = []

    def _call(target, operation, arguments):
        calls.append((target.adapter, operation, dict(arguments)))
        return V2_PAGE

    with patch("skills.jira.mutations.atlassian_mcp_jira_call", side_effect=_call):
        result = _search("assignee = currentUser()", 5)

    assert calls == [("atlassian-mcp", "search_issues", {
        "jql": "assignee = currentUser()", "maxResults": 5,
        "fields": ["summary", "status", "priority", "assignee"]})]
    assert result["issues"][0] == {
        "key": "GFX-1", "summary": "First", "status": "Open", "priority": "P2",
        "assignee": "Maple, Jarrad", "url": f"{SITE}/browse/GFX-1"}
    assert result["issues"][1]["assignee"] == "Unassigned" and result["issues"][1]["priority"] == ""
    assert result["total"] == 2 and result["more_available"] is True


def test_atlassian_mcp_search_page_size_is_capped_at_the_servers_maximum():
    with patch("skills.jira.mutations.atlassian_mcp_jira_call", return_value={"issues": [], "isLast": True}) as call:
        result = _search(max_results=500)
    assert call.call_args.args[2]["maxResults"] == 100
    assert "more_available" not in result


def test_connection_without_a_search_tool_reports_it_instead_of_guessing():
    err = JiraTargetResolutionError("The selected Atlassian MCP connection does not support search issues.")
    with patch("skills.jira.mutations.atlassian_mcp_jira_call", side_effect=err):
        result = _search()
    assert "does not support search issues" in result["error"] and result["site"] == SITE
    assert "issues" not in result


def test_unreadable_atlassian_mcp_reply_is_an_error_not_an_empty_result():
    with patch("skills.jira.mutations.atlassian_mcp_jira_call", return_value="plain text"):
        result = _search()
    assert "unreadable" in result["error"] and "issues" not in result


def _atlassian_mcp_run(tools_list, client):
    connection = {"id": "conn-1", "enabled": True, "cached_tools": tools_list}
    with patch("mcp.manager._load_connections", return_value=[connection]), \
         patch("mcp.manager._client_for", return_value=client):
        return atlassian_mcp_jira_call(ATLASSIAN_MCP_SITE, "search_issues", {"jql": "project = GFX", "maxResults": 3, "fields": ["summary"]})


def _tool(name, **hints):
    tool = {"name": name, "input_schema": {"type": "object", "properties": {"cloudId": {}, "jql": {}}}}
    if hints:
        tool["annotations"] = hints
    return tool


def _client():
    client = MagicMock()
    client.call.side_effect = lambda tool, args: (
        json.dumps({"data": {"resources": [{"cloudId": CLOUD_ID, "url": SITE}]}})
        if tool == "getAccessibleAtlassianResources"
        else json.dumps({"data": V2_PAGE}))
    return client


def test_adapter_runs_the_direct_search_tool_for_the_captured_site():
    client = _client()
    result = _atlassian_mcp_run([_tool("getAccessibleAtlassianResources"), _tool("searchJiraIssuesUsingJql", readOnlyHint=True)], client)
    assert result == V2_PAGE
    name, args = client.call.call_args.args
    assert name == "searchJiraIssuesUsingJql"
    assert args == {"jql": "project = GFX", "maxResults": 3, "fields": ["summary"], "cloudId": CLOUD_ID}


def test_adapter_refuses_a_search_tool_the_server_says_writes():
    client = _client()
    with pytest.raises(JiraTargetResolutionError, match="not a read operation"):
        _atlassian_mcp_run([_tool("getAccessibleAtlassianResources"),
                   _tool("searchJiraIssuesUsingJql", readOnlyHint=False, destructiveHint=False)], client)


def test_adapter_without_the_tool_or_discovery_does_not_support_search():
    with pytest.raises(JiraTargetResolutionError, match="does not support search issues"):
        _atlassian_mcp_run([_tool("getAccessibleAtlassianResources"), _tool("getJiraIssue")], _client())
