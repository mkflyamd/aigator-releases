"""Raw Jira MCP writes (e.g. Rovo's executeWrite) are parked as an approval card.

The handler never reaches the MCP client for a write; the call only runs from the
CSRF-gated /api/drafts/{id}/approve endpoint. Reads pass straight through.
"""

import json
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).parent.parent / "web"))

from unittest.mock import MagicMock, patch

import shared
from app import app
from fastapi.testclient import TestClient
from mcp import manager
from skills import _drafts

OFFICIAL = {"id": "rovo", "name": "Atlassian Rovo", "transport": "http", "url": "https://mcp.atlassian.com/v2/mcp"}
OFF_HOST = {"id": "fake", "name": "Atlassian Jira helper", "transport": "http", "url": "https://evil.example.com/mcp"}
SCHEMA = {"type": "object", "properties": {}}


def setup_function(function):
    _drafts._pending_drafts.clear()


def _handlers(conn, tools):
    conn = {**conn, "cached_tools": tools}
    shared.TOOL_DISPATCH.clear()
    shared.TOOLS.clear()
    shared.TOOL_STATUS.clear()
    shared.SKILL_TOOLS_MAP.pop(conn["id"], None)
    manager._register(conn)
    by_raw = {}
    for alias in shared.SKILL_TOOLS_MAP[conn["id"]]:
        for tool in tools:
            if tool["name"].lower() in alias.lower():
                by_raw[tool["name"]] = shared.TOOL_DISPATCH[alias]
    return by_raw


def _tool(name, **hints):
    tool = {"name": name, "description": name, "input_schema": SCHEMA}
    if hints:
        tool["annotations"] = hints
    return tool


def _approve(draft_id):
    from security import get_csrf_token

    return TestClient(app).post(
        f"/api/drafts/{draft_id}/approve",
        headers={"X-CSRF-Token": get_csrf_token("testserver")},
        json=None,
    )


WRITE_HINTS = {"readOnlyHint": False, "destructiveHint": False}


def test_a_raw_write_is_parked_as_a_draft_and_never_reaches_the_server():
    handlers = _handlers(OFFICIAL, [_tool("executeWrite", **WRITE_HINTS)])
    with patch("mcp.manager._client_for") as client_for:
        result = handlers["executeWrite"](toolName="editJiraIssue", cloudId="c1", issueIdOrKey="ROCMAI-845")
    client_for.assert_not_called()
    assert result["_draft"] == "jira-mcp-write" and "terminal" not in result and "error" not in result
    data = result["data"]
    assert data["tool"] == "executeWrite" and data["connection"] == "Atlassian Rovo"
    assert "editJiraIssue" in data["action"] and "ROCMAI-845" in data["arguments_text"]
    assert "approve" in result["_user_message"].lower()
    stored = _drafts.get_draft(data["draft_id"])
    assert stored["params"]["connection_id"] == "rovo"
    assert stored["params"]["arguments"]["issueIdOrKey"] == "ROCMAI-845"


def test_a_write_on_a_server_that_only_claims_to_be_atlassian_is_also_a_card_not_a_bypass():
    handlers = _handlers(OFF_HOST, [_tool("executeRead", readOnlyHint=True, destructiveHint=False)])
    with patch("mcp.manager._client_for") as client_for:
        result = handlers["executeRead"](toolName="deleteEverything")
    client_for.assert_not_called()
    assert result["_draft"] == "jira-mcp-write"


def test_reads_are_not_carded():
    handlers = _handlers(OFFICIAL, [_tool("executeRead", readOnlyHint=True, destructiveHint=False)])
    client = MagicMock()
    client.call.return_value = '{"data": {}}'
    with patch("mcp.manager._client_for", return_value=client):
        result = handlers["executeRead"](toolName="getJiraIssue")
    client.call.assert_called_once()
    assert "_draft" not in result


def test_the_card_shows_every_argument_the_approval_will_send():
    handlers = _handlers(OFFICIAL, [_tool("executeWrite", **WRITE_HINTS)])
    result = handlers["executeWrite"](toolName="editJiraIssue", body="x" * 5000 + "TAIL")
    stored = _drafts.get_draft(result["data"]["draft_id"])["params"]["arguments"]
    assert json.loads(result["data"]["arguments_text"]) == stored
    assert "TAIL" in result["data"]["arguments_text"]


def test_a_classification_word_in_the_arguments_raises_the_sensitivity_warning():
    from data_sources import sensitivity_markers

    handlers = _handlers(OFFICIAL, [_tool("executeWrite", **WRITE_HINTS)])
    result = handlers["executeWrite"](toolName="addComment", body="AMD Restricted roadmap")
    assert sensitivity_markers(result["data"]) == ["AMD Restricted"]


def test_approving_the_card_runs_the_stored_call_once():
    handlers = _handlers(OFFICIAL, [_tool("executeWrite", **WRITE_HINTS)])
    draft_id = handlers["executeWrite"](toolName="editJiraIssue", issueIdOrKey="ROCMAI-845")["data"]["draft_id"]
    client = MagicMock()
    client.call.return_value = '{"data": {"updated": true}}'
    with patch("mcp.manager._load_connections", return_value=[OFFICIAL]), \
         patch("mcp.manager._client_for", return_value=client):
        response = _approve(draft_id)
    assert response.status_code == 200, response.text
    client.call.assert_called_once_with("executeWrite", {"toolName": "editJiraIssue", "issueIdOrKey": "ROCMAI-845"})
    assert response.json()["ok"] is True
    assert _drafts.get_draft(draft_id) is None


def test_approval_works_with_a_client_that_needs_its_own_event_loop():
    import asyncio

    class LoopHungryClient:
        """Like the HTTP MCP client: call() uses asyncio.run(), which fails on a running loop."""

        def call(self, tool, arguments):
            asyncio.run(asyncio.sleep(0))
            return "done"

    handlers = _handlers(OFFICIAL, [_tool("editJiraIssue", **WRITE_HINTS)])
    draft_id = handlers["editJiraIssue"](issueIdOrKey="ROCMAI-845")["data"]["draft_id"]
    with patch("mcp.manager._load_connections", return_value=[OFFICIAL]), \
         patch("mcp.manager._client_for", return_value=LoopHungryClient()):
        response = _approve(draft_id)
    assert response.status_code == 200, response.text
    assert response.json()["result"] == "done"


def test_approving_after_the_connection_was_removed_is_refused_without_a_call():
    handlers = _handlers(OFFICIAL, [_tool("executeWrite", **WRITE_HINTS)])
    draft_id = handlers["executeWrite"](toolName="editJiraIssue")["data"]["draft_id"]
    with patch("mcp.manager._load_connections", return_value=[]), \
         patch("mcp.manager._client_for") as client_for:
        response = _approve(draft_id)
    assert response.status_code == 404
    client_for.assert_not_called()


def test_the_card_is_wired_in_the_ui():
    source = (pathlib.Path(__file__).parent.parent / "web" / "static" / "app.js").read_text(encoding="utf-8")
    assert "'jira-mcp-write': {" in source and "escapeHtml(data.arguments_text" in source
