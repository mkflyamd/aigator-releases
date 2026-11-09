"""Raw MCP Jira calls: only Atlassian's own server may vouch for a read through its hints.

Writes need an approval card on every connection. On the official host the server's
readOnlyHint decides; anywhere else a hint proves nothing and the tool name rule applies.
"""

import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).parent.parent / "web"))

from unittest.mock import MagicMock, patch

import pytest
import shared
from mcp import manager

OFFICIAL = {"id": "atlassian-mcp", "name": "Atlassian MCP", "url": "https://mcp.atlassian.com/v2/mcp"}
READ = {"readOnlyHint": True, "destructiveHint": False}
WRITE = {"readOnlyHint": False, "destructiveHint": False}
DESTRUCTIVE = {"readOnlyHint": False, "destructiveHint": True}


def blocked(name, conn=OFFICIAL, hints=None):
    return manager._is_unverified_jira_mcp_mutation(name, conn, hints)


def test_official_host_read_hint_unblocks_v2_reads_the_name_rule_would_refuse():
    assert blocked("executeRead") and blocked("discover")
    assert not blocked("executeRead", hints=READ)
    assert not blocked("discover", hints=READ)


def test_official_host_write_and_destructive_hints_stay_refused():
    assert blocked("executeWrite", hints=WRITE)
    assert blocked("executeDestructive", hints=DESTRUCTIVE)
    assert blocked("executeRead", hints={"readOnlyHint": True, "destructiveHint": True})


def test_read_looking_name_is_refused_when_the_servers_hint_says_otherwise():
    assert not blocked("getJiraIssue")  # unhinted, the name alone would have allowed it
    assert blocked("getJiraIssue", hints=WRITE)
    assert blocked("searchJiraIssuesUsingJql", hints=DESTRUCTIVE)
    assert blocked("fetchAndTransitionJiraIssue", hints=WRITE)


def test_official_host_without_hints_uses_the_name_rule():
    assert not blocked("getJiraIssue", hints={})
    assert blocked("createJiraIssue", hints={})
    assert blocked("executeRead", hints={"idempotentHint": True})


@pytest.mark.parametrize(
    "url",
    [
        "https://evil.example.com/mcp",
        "https://mcp.atlassian.com.evil.example/v2/mcp",
        "http://mcp.atlassian.com/v2/mcp",
        "https://evil.example/?next=https://mcp.atlassian.com/",
        "",
    ],
)
def test_hints_from_any_other_server_are_not_trusted(url):
    conn = {"id": "fake", "name": "Atlassian Jira helper", "url": url}
    assert blocked("executeRead", conn, READ)
    assert blocked("performAction", conn, READ)
    assert blocked("createJiraIssue", conn, READ)
    assert not blocked("getJiraIssue", conn, READ)  # the name rule still serves plain reads


def test_registered_handler_uses_the_hints_end_to_end(monkeypatch):
    monkeypatch.setattr(shared, "TOOL_DISPATCH", {})
    monkeypatch.setattr(shared, "TOOLS", [])
    monkeypatch.setattr(shared, "TOOL_STATUS", {})
    monkeypatch.setattr(shared, "SKILL_TOOLS_MAP", {})
    schema = {"type": "object", "properties": {}}
    conn = {
        **OFFICIAL,
        "transport": "http",
        "cached_tools": [
            {"name": "executeRead", "description": "r", "input_schema": schema, "annotations": READ},
            {"name": "executeWrite", "description": "w", "input_schema": schema, "annotations": WRITE},
        ],
    }
    manager._register(conn)
    aliases = {
        raw: alias
        for alias in shared.SKILL_TOOLS_MAP["atlassian-mcp"]
        for raw in ("executeRead", "executeWrite")
        if raw.lower() in alias.lower()
    }
    client = MagicMock()
    client.call.return_value = '{"data": {"ok": true}}'
    with patch("mcp.manager._client_for", return_value=client):
        parked = shared.TOOL_DISPATCH[aliases["executeWrite"]]()
        assert parked["_draft"] == "jira-mcp-write" and "terminal" not in parked
        client.call.assert_not_called()
        allowed = shared.TOOL_DISPATCH[aliases["executeRead"]]()
    assert "terminal" not in str(allowed)
    client.call.assert_called_once()


def test_a_connection_saved_under_the_old_product_name_stays_gated():
    legacy = {"name": "Rovo", "url": "https://proxy.example.com/sse"}
    assert manager._is_atlassian_connection(legacy)
    assert blocked("createJiraIssue", legacy)
    assert not blocked("getJiraIssue", legacy)
    assert blocked("rovo_fetch_and_transition_issue", legacy)
