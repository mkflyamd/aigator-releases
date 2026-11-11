import asyncio
import pathlib
import sys
from types import SimpleNamespace

sys.path.insert(0, str(pathlib.Path(__file__).parent.parent / "web"))

import pytest

import app  # noqa: F401  (builds the tool registry)
import data_sources as ds
import permissions
import shared
from agent_loop import _make_tool_runner
from browser_agent import resolve_browser_confirm
from permissions import actions, registry


@pytest.fixture(autouse=True)
def _fresh():
    ds._reset()
    yield
    ds._reset()


def _native_tools():
    names = set()
    for skill_id in ds._NATIVE_SOURCES:
        names |= set(shared.SKILL_TOOLS_MAP.get(skill_id, ()))
    return names


def test_every_built_in_tool_has_an_action_type():
    missing = sorted(_native_tools() - set(actions.BUILTIN_ACTIONS))
    assert not missing, f"classify these tools in web/permissions/actions.py: {missing}"


def test_the_action_table_names_only_tools_that_exist():
    assert sorted(set(actions.BUILTIN_ACTIONS) - _native_tools()) == []


def test_every_action_type_is_one_of_the_four():
    assert set(actions.BUILTIN_ACTIONS.values()) <= set(actions.ALL)


def test_a_tool_nobody_classified_is_irreversible():
    assert actions.action_for_call("brand_new_tool") == actions.IRREVERSIBLE
    assert actions.gate_action("brand_new_tool") is None


@pytest.mark.parametrize("tool", ["send_email", "reply_email", "forward_email", "send_teams_message",
                                  "slack_send_message", "jira_add_comment", "jira_add_watcher"])
def test_messages_and_notifying_jira_changes_are_irreversible_and_draft_backed(tool):
    assert actions.BUILTIN_ACTIONS[tool] == actions.IRREVERSIBLE
    assert tool in actions.DRAFT_BACKED
    assert actions.gate_action(tool) == actions.WRITE_PRIVATE


@pytest.mark.parametrize("tool", ["delete_calendar_event", "respond_calendar_event", "update_calendar_event",
                                  "add_calendar_attendees", "delete_contact", "github_create_issue",
                                  "github_add_issue_comment"])
def test_direct_irreversible_tools_have_no_remembered_gate(tool):
    assert actions.BUILTIN_ACTIONS[tool] == actions.IRREVERSIBLE
    assert actions.gate_action(tool) is None


def test_a_calendar_event_with_attendees_notifies_and_one_without_does_not():
    assert actions.action_for_call("create_calendar_event", {"subject": "x"}) == actions.WRITE_PRIVATE
    assert actions.action_for_call("create_calendar_event", {"attendees": ["a@b.c"]}) == actions.IRREVERSIBLE
    assert actions.action_for_call("create_calendar_event", {"optional_attendees": "a@b.c"}) == actions.IRREVERSIBLE
    assert actions.gate_action("create_calendar_event", {"attendees": ["a@b.c"]}) is None


def test_github_gh_is_read_only_only_for_a_read_command():
    assert actions.action_for_call("github_gh", {"args": ["issue", "list"]}) == actions.READ
    assert actions.action_for_call("github_gh", {"args": ["issue", "create", "-t", "x"]}) == actions.IRREVERSIBLE
    assert actions.action_for_call("github_gh", {}) == actions.IRREVERSIBLE


def test_reading_and_private_and_reversible_writes_can_be_remembered():
    assert actions.gate_action("search_email") == actions.READ
    assert actions.gate_action("create_onenote_page") == actions.WRITE_PRIVATE
    assert actions.gate_action("update_confluence_page") == actions.WRITE_PUBLIC


def test_no_category_is_offered_for_the_irreversible_type():
    ids = {c.id for c in registry.known()}
    assert not [i for i in ids if i.endswith(":" + actions.IRREVERSIBLE)]
    assert permissions.card_options("data:Outlook calendar:irreversible") is None
    assert registry.get("data:Slack:irreversible") is None


def test_each_app_lists_a_category_per_action_type_its_tools_can_use():
    ids = {c.id for c in registry.known()}
    assert {"data:Outlook mail:read", "data:Outlook mail:write_private", "data:Outlook calendar:read",
            "data:Outlook calendar:write_private", "data:Confluence:write_public",
            "data:GitHub:read"} <= ids
    assert "data:Outlook mail:write_public" not in ids


def _tc(name, inputs=None, call_id="c1"):
    return SimpleNamespace(id=call_id, name=name, inputs=inputs or {})


def _runner(calls, context_id="tab-a"):
    async def execute_tool(name, inputs):
        calls.append(name)
        return {"ok": True}

    run, _, _ = _make_tool_runner(execute_tool, frozenset(), {}, lambda n, r: None, "safe", context_id=context_id)
    return run


async def _answer(queue, scope, cards):
    while True:
        evt = await asyncio.wait_for(queue.get(), 5)
        if evt["kind"] == "browser_confirm":
            cards.append(evt)
            resolve_browser_confirm(evt["confirm_id"], True, scope)
            return


def _allow_everything_else_for(label):
    for category in registry.known():
        if category.id.startswith(f"data:{label}:"):
            permissions.remember(category.id)
            ds.allow("tab-a", category.id)


@pytest.mark.parametrize("tool,inputs,label", [
    ("delete_calendar_event", {"event_id": "e1"}, "Outlook calendar"),
    ("respond_calendar_event", {"event_id": "e1", "response": "accept"}, "Outlook calendar"),
    ("create_calendar_event", {"subject": "x", "attendees": ["a@b.c"]}, "Outlook calendar"),
    ("delete_contact", {"contact_id": "c1"}, "Outlook contacts"),
    ("github_create_issue", {"repo": "o/r", "title": "x"}, "GitHub"),
    ("github_add_issue_comment", {"repo": "o/r", "number": 1, "body": "x"}, "GitHub"),
])
async def test_an_irreversible_tool_still_asks_when_every_other_category_for_the_app_is_always_allowed(
        tool, inputs, label):
    _allow_everything_else_for(label)
    calls, cards, q = [], [], asyncio.Queue()
    run = _runner(calls)
    res, _ = await asyncio.gather(run(_tc(tool, inputs), q), _answer(q, "once", cards))
    assert res.get("ok") is True and calls == [tool]
    assert cards and cards[0]["title"].startswith("Allow this change in")
    assert cards[0]["allow_label"] == "Allow this time"
    assert cards[0].get("category") is None


async def test_the_same_irreversible_tool_asks_again_on_the_next_call():
    calls, cards, q = [], [], asyncio.Queue()
    run = _runner(calls)
    await asyncio.gather(run(_tc("delete_calendar_event", {"event_id": "e1"}), q), _answer(q, "tab", cards))
    q2 = asyncio.Queue()
    await asyncio.gather(run(_tc("delete_calendar_event", {"event_id": "e2"}, "c2"), q2), _answer(q2, "tab", cards))
    assert len(cards) == 2


async def test_choosing_tab_or_always_on_an_irreversible_card_remembers_nothing():
    calls, cards, q = [], [], asyncio.Queue()
    await asyncio.gather(_runner(calls)(_tc("delete_contact", {"contact_id": "c1"}), q), _answer(q, "always", cards))
    assert not ds.allowed_with_prefix("tab-a", "data:")
    assert permissions.decision("tab-z", "data:Outlook contacts:irreversible") == "ask"
    assert permissions.decision("tab-z", "data:Outlook contacts:read") == "ask"


async def test_reading_an_app_does_not_unlock_writing_to_it():
    permissions.remember("data:Outlook mail:read")
    calls, cards, q = [], [], asyncio.Queue()
    await asyncio.gather(_runner(calls, "tab-z")(_tc("email_open_compose", {}), q), _answer(q, "once", cards))
    assert cards and cards[0]["title"] == "Allow changes in Outlook mail?"


def _hints_classifier(hints, name="tool"):
    from mcp.manager import _make_classifier

    return _make_classifier(name, {"name": "srv", "url": "https://mcp.example.test"}, hints)


def test_an_mcp_tool_is_read_only_only_when_the_server_declares_it():
    assert _hints_classifier({"readOnlyHint": True})({}) == "read"
    assert _hints_classifier({})({}) == "other"
    assert _hints_classifier({"readOnlyHint": False})({}) == "other"
    assert _hints_classifier({"readOnlyHint": True, "destructiveHint": True})({}) == "other"


def test_an_mcp_tool_with_no_classifier_asks_every_call():
    assert ds._mcp_gate("srv__unknown", {}) is None


def test_mcp_categories_exist_only_for_read_and_private_writes():
    assert registry.mcp_category("mcp:srv:read") is not None
    assert registry.mcp_category("mcp:srv:write_private") is not None
    for bad in ("mcp:srv", "mcp:srv:write_public", "mcp:srv:irreversible", "mcp::read", "mcp:", "data:srv:read"):
        assert registry.mcp_category(bad) is None, bad


def test_mcp_calls_are_filed_by_what_the_server_declares(monkeypatch):
    monkeypatch.setitem(shared.SKILL_TOOLS_MAP, "mcp-srv", ["srv__list", "srv__send", "srv__park", "srv__plain"])
    monkeypatch.setitem(shared.MCP_TOOL_CLASSIFIERS, "srv__list", lambda kw: "read")
    monkeypatch.setitem(shared.MCP_TOOL_CLASSIFIERS, "srv__park", lambda kw: "draft")
    monkeypatch.setitem(shared.MCP_TOOL_CLASSIFIERS, "srv__send", lambda kw: "other")

    read = ds.source_for_call("srv__list", {})
    assert read.key == "mcp:mcp-srv:read" and not read.per_call
    parked = ds.source_for_call("srv__park", {})
    assert parked.key == "mcp:mcp-srv:write_private" and not parked.per_call
    for name in ("srv__send", "srv__plain"):
        source = ds.source_for_call(name, {})
        assert source.per_call and source.key == "mcp:mcp-srv:irreversible"
