import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

import app  # noqa: F401  (builds the tool registry)
import data_sources as ds
from routes import conversation_routes


@pytest.fixture(autouse=True)
def _fresh():
    ds._reset()
    yield
    ds._reset()


def test_native_tools_map_to_their_source():
    assert ds.source_for_call("search_email", {}).label == "Outlook mail"
    assert ds.source_for_call("read_channel_messages", {}).label == "Microsoft Teams"
    assert ds.source_for_call("jira_search", {}).label == "Jira"
    assert ds.source_for_call("search_confluence", {}).label == "Confluence"
    assert ds.source_for_call("slack_search_public_and_private", {}).label == "Slack"
    assert ds.source_for_call("search_onedrive_files", {}).key == ds.source_for_call("list_sharepoint_sites", {}).key


def test_mcp_tools_map_to_one_source_per_server(monkeypatch):
    # No MCP server is registered in the test environment, so register two fake tools
    # shaped like the real registration: the server's own skill id holds every tool and
    # smaller synthetic service groups (g-gmail, g-drive) hold subsets.
    gmail = "mcp-google-workspace_aaaaaaaaaa__search_gmail_messages"
    drive = "mcp-google-workspace_bbbbbbbbbb__search_drive_files"
    skill_map = app.shared.SKILL_TOOLS_MAP
    monkeypatch.setitem(app.shared.TOOL_DISPATCH, gmail, lambda **kw: {})
    monkeypatch.setitem(app.shared.TOOL_DISPATCH, drive, lambda **kw: {})
    monkeypatch.setitem(skill_map, "mcp-google-workspace", {gmail, drive})
    monkeypatch.setitem(skill_map, "g-gmail", {gmail})
    monkeypatch.setitem(skill_map, "g-drive", {drive})
    a, b = ds.source_for_call(gmail, {}), ds.source_for_call(drive, {})
    assert a.label == "Google Workspace" and a.key == b.key


def test_tools_that_read_no_external_source_have_no_source():
    for name in ("run_python", "read_skill", "web_search", "create_docx", "read_file"):
        assert ds.source_for_call(name, {}) is None


def test_fetch_webpage_source_is_the_host():
    s = ds.source_for_call("fetch_webpage", {"url": "https://Example.com/a?b=1"})
    assert s.kind == "web" and s.key == "web:example.com" and "example.com" in s.label
    assert ds.source_for_call("fetch_webpage", {"url": "not a url"}) is None


def test_untrusted_tools():
    assert ds.is_untrusted("fetch_webpage") and ds.is_untrusted("web_search")
    assert ds.is_untrusted("read_email") and ds.is_untrusted("jira_get_issue")
    assert not ds.is_untrusted("run_python") and not ds.is_untrusted("create_docx")


def test_prompt_text_names_the_source_and_the_tool():
    s = ds.source_for_call("search_email", {})
    p = ds.prompt_for(s, "search_email")
    assert "Outlook mail" in p["title"] and "search_email" in p["action"]
    assert p["allow_label"] == "Allow for this tab" and p["deny_label"] == "Deny"


def test_allow_is_per_tab_and_ends_with_the_tab():
    ds.allow("tab-a", "data:Jira")
    assert ds.is_allowed("tab-a", "data:Jira")
    assert not ds.is_allowed("tab-b", "data:Jira")
    ds.end_for_tab("tab-a")
    assert not ds.is_allowed("tab-a", "data:Jira")


def test_a_denial_is_remembered_only_briefly():
    ds.deny("tab-a", "data:Jira")
    assert ds.recently_denied("tab-a", "data:Jira")
    assert not ds.recently_denied("tab-a", "data:Jira", window_s=0.0)
    assert not ds.recently_denied("tab-b", "data:Jira")


def test_closing_a_tab_ends_its_source_approvals():
    api = FastAPI()
    api.include_router(conversation_routes.router)
    ds.allow("tab-a", "data:Jira")
    ds.allow("tab-b", "data:Jira")
    assert TestClient(api).delete("/api/conversation/tab-a").status_code == 200
    assert not ds.is_allowed("tab-a", "data:Jira")
    assert ds.is_allowed("tab-b", "data:Jira")
