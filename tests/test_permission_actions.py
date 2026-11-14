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


# Built-in tools outside the data-source apps. None asks through a data-source card: shell, code, browser, file and
# Office tools have their own capability or sandbox cards; the rest act only on local state or fetch a public page.
NO_GATE = frozenset("""
connect_mcp_server read_skill list_schedules fetch_webpage web_search analyze_mcp_server schedule_task ask_user
request_skill describe_images mcp_connection_status
browser_navigate browser_task browser_search
get_code_changes run_python run_shell stop_shell_process check_shell_process
get_docx_info update_docx read_docx create_docx
recalc_excel get_excel_info update_excel create_excel list_excel_sheets read_excel
pptx_add_autoshape get_pptx_info create_pptx pptx_write_table_cell pptx_replace_picture pptx_list_shapes
pptx_apply_theme pptx_set_shape pptx_add_hyperlink update_pptx pptx_read_table read_pptx pptx_add_table_row
fetch_image read_file write_file grep_files list_dir glob_files edit_file
demo_speed_interval demo_merge_narration demo_replace_interval demo_append_clip demo_media_manifest
demo_inspect_frames demo_cut_intervals
pin_item get_tab_pins get_skill_content list_skills update_skill create_skill
""".split())


def _every_built_in_tool():
    return {t for tools in shared.SKILL_TOOLS_MAP.values() for t in tools if "__" not in t}


def test_every_built_in_tool_is_classified_or_reviewed_as_having_no_data_source():
    unreviewed = sorted(_every_built_in_tool() - set(actions.BUILTIN_ACTIONS) - NO_GATE)
    assert not unreviewed, f"classify in web/permissions/actions.py, or add to NO_GATE here after review: {unreviewed}"


def test_the_no_gate_list_names_only_unclassified_tools_that_exist():
    assert sorted(NO_GATE - _every_built_in_tool()) == []
    assert sorted(NO_GATE & set(actions.BUILTIN_ACTIONS)) == []


def test_every_action_type_is_one_of_the_four():
    assert set(actions.BUILTIN_ACTIONS.values()) <= set(actions.ALL)


def test_a_tool_nobody_classified_is_irreversible():
    assert actions.action_for_call("brand_new_tool") == actions.IRREVERSIBLE
    assert actions.gate_action("brand_new_tool") is None


@pytest.mark.parametrize("tool", ["send_email", "reply_email", "forward_email", "send_teams_message",
                                  "slack_send_message", "jira_add_comment", "jira_add_watcher", "jira_update_issue",
                                  "jira_transition", "jira_link_issues"])
def test_messages_and_notifying_jira_changes_are_irreversible_and_draft_backed(tool):
    assert actions.BUILTIN_ACTIONS[tool] == actions.IRREVERSIBLE
    assert tool in actions.DRAFT_BACKED
    assert actions.gate_action(tool) == actions.WRITE_PRIVATE


@pytest.mark.parametrize("tool", ["delete_calendar_event", "respond_calendar_event", "update_calendar_event",
                                  "add_calendar_attendees", "delete_contact", "github_create_issue",
                                  "github_add_issue_comment", "update_confluence_page", "create_confluence_page"])
def test_direct_irreversible_tools_have_no_remembered_gate(tool):
    assert actions.BUILTIN_ACTIONS[tool] == actions.IRREVERSIBLE
    assert actions.gate_action(tool) is None


def test_a_calendar_event_with_attendees_notifies_and_one_without_does_not():
    assert actions.action_for_call("create_calendar_event", {"subject": "x"}) == actions.WRITE_PRIVATE
    assert actions.action_for_call("create_calendar_event", {"attendees": ["a@b.c"]}) == actions.IRREVERSIBLE
    assert actions.action_for_call("create_calendar_event", {"optional_attendees": "a@b.c"}) == actions.IRREVERSIBLE
    assert actions.gate_action("create_calendar_event", {"attendees": ["a@b.c"]}) is None


def test_a_file_moved_within_one_drive_can_be_undone_and_one_moved_across_drives_cannot():
    same = {"source_drive_id": "d1", "dest_drive_id": "d1"}
    for tool in ("move_onedrive_file", "copy_onedrive_file"):
        assert actions.action_for_call(tool, same) == actions.WRITE_PUBLIC
        assert actions.action_for_call(tool, {**same, "dest_drive_id": "d2"}) == actions.IRREVERSIBLE
        assert actions.action_for_call(tool, {"source_drive_id": "d1"}) == actions.IRREVERSIBLE
        assert actions.action_for_call(tool, {}) == actions.IRREVERSIBLE
        assert actions.gate_action(tool, {**same, "dest_drive_id": "d2"}) is None
        assert actions.gate_actions_possible(tool) == {actions.WRITE_PUBLIC}


def test_onenote_created_in_a_team_site_is_visible_to_others():
    for tool in ("create_onenote_notebook", "create_onenote_section", "create_onenote_page"):
        assert actions.action_for_call(tool, {"title": "x"}) == actions.WRITE_PRIVATE
        assert actions.action_for_call(tool, {"site_id": "  "}) == actions.WRITE_PRIVATE
        assert actions.action_for_call(tool, {"site_id": "s1"}) == actions.WRITE_PUBLIC
        assert actions.gate_actions_possible(tool) == {actions.WRITE_PRIVATE, actions.WRITE_PUBLIC}


def test_each_permission_a_call_can_be_filed_under_is_offered_for_the_app():
    ids = {c.id for c in registry.known()}
    assert "data:SharePoint and OneDrive:write_public" in ids
    assert {"data:OneNote:write_private", "data:OneNote:write_public"} <= ids
    assert actions.gate_actions_possible("create_calendar_event") == {actions.WRITE_PRIVATE}
    assert actions.gate_actions_possible("github_gh") == {actions.READ}


def test_github_gh_is_read_only_only_for_a_read_command():
    assert actions.action_for_call("github_gh", {"args": ["issue", "list"]}) == actions.READ
    assert actions.action_for_call("github_gh", {"args": ["issue", "create", "-t", "x"]}) == actions.IRREVERSIBLE
    assert actions.action_for_call("github_gh", {}) == actions.IRREVERSIBLE


def test_reading_and_private_and_reversible_writes_can_be_remembered():
    assert actions.gate_action("search_email") == actions.READ
    assert actions.gate_action("create_onenote_page") == actions.WRITE_PRIVATE
    assert actions.gate_action("update_onenote_page") == actions.WRITE_PUBLIC


def test_no_category_is_offered_for_the_irreversible_type():
    ids = {c.id for c in registry.known()}
    assert not [i for i in ids if i.endswith(":" + actions.IRREVERSIBLE)]
    assert permissions.card_options("data:Outlook calendar:irreversible") is None
    assert registry.get("data:Slack:irreversible") is None


def test_each_app_lists_a_category_per_action_type_its_tools_can_use():
    ids = {c.id for c in registry.known()}
    assert {"data:Outlook mail:read", "data:Outlook mail:write_private", "data:Outlook calendar:read",
            "data:Outlook calendar:write_private", "data:OneNote:write_public",
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
    ("update_calendar_event", {"event_id": "e1"}, "Outlook calendar"),
    ("move_onedrive_file", {"source_drive_id": "d1", "dest_drive_id": "d2"}, "SharePoint and OneDrive"),
    ("update_confluence_page", {"page_id": "1"}, "Confluence"),
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


async def test_an_irreversible_card_remembers_nothing_even_if_a_tab_or_always_answer_arrives():
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


async def test_an_unattended_run_refuses_a_call_that_needs_its_own_approval():
    calls = []
    res = await _runner(calls, context_id=None)(_tc("delete_calendar_event", {"event_id": "e1"}), asyncio.Queue())
    assert res["error"] == "irreversible_not_allowed_unattended" and calls == []


async def test_an_unattended_run_can_still_stage_a_draft_for_an_irreversible_action():
    calls = []
    res = await _runner(calls, context_id=None)(_tc("jira_transition", {"issue_key": "AB-1"}), asyncio.Queue())
    assert res.get("ok") is True and calls == ["jira_transition"]


async def test_an_unattended_run_refuses_an_mcp_tool_that_does_not_declare_itself_read_only(monkeypatch):
    monkeypatch.setitem(shared.SKILL_TOOLS_MAP, "mcp-srv", ["srv__send"])
    monkeypatch.setitem(shared.MCP_TOOL_CLASSIFIERS, "srv__send", lambda kw: "other")
    calls = []
    res = await _runner(calls, context_id=None)(_tc("srv__send", {}), asyncio.Queue())
    assert res["error"] == "irreversible_not_allowed_unattended" and calls == []


ATLASSIAN = {"name": "atlassian", "url": "https://mcp.atlassian.com/v1/sse"}
OTHER = {"name": "srv", "url": "https://mcp.example.test"}


def _hints_classifier(hints, conn=ATLASSIAN, name="getJiraIssue"):
    from mcp.manager import _make_classifier

    return _make_classifier(name, conn, hints)


def test_a_read_only_hint_is_trusted_from_any_server():
    for conn in (ATLASSIAN, OTHER, {"name": "x", "url": "http://mcp.atlassian.com/"}):
        assert _hints_classifier({"readOnlyHint": True}, conn)({}) == "read"
        assert _hints_classifier({}, conn)({}) == "other"


def test_an_mcp_tool_is_read_only_only_when_the_server_declares_it():
    for conn in (ATLASSIAN, OTHER):
        assert _hints_classifier({"readOnlyHint": True}, conn)({}) == "read"
        assert _hints_classifier({}, conn)({}) == "other"
        for hints in ({"readOnlyHint": False}, {"readOnlyHint": True, "destructiveHint": True},
                      {"readOnlyHint": "true"}):
            assert _hints_classifier(hints, conn)({}) != "read"
    assert _hints_classifier({"readOnlyHint": False}, OTHER)({}) == "other"
    assert _hints_classifier({"readOnlyHint": "true"}, OTHER)({}) == "other"


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


def test_the_card_shows_the_arguments_of_the_call():
    inputs = {"attendees": [f"person{i}@example.test" for i in range(20)]}
    details = ds._call_details(inputs)
    assert "person19@example.test" in details and "not shown" not in details
    assert ds._call_details({"event_id": "e1"}) == '\nDetails: {"event_id": "e1"}'
    assert ds._call_details({}) == ""


def test_a_long_value_is_cut_on_the_card_and_says_how_much_is_hidden():
    details = ds._call_details({"body": "x" * 5000})
    assert len(details) < ds._CARD_VALUE_MAX + 100
    assert details.endswith("more characters not shown)}")


def test_a_long_value_cannot_push_the_recipient_off_the_card():
    details = ds._call_details({"body": "x" * 5000, "attendees": ["victim@example.test"]})
    assert '"attendees": ["victim@example.test"]' in details


def test_the_card_stays_on_one_line_and_hides_text_direction_tricks_and_invisible_characters():
    tricks = [chr(c) for c in (0x202E, 0x2028, 0x200B, 0x85, 0x1B)]
    details = ds._call_details({"to": "a@b.c" + "".join(tricks) + " fake line"})
    assert chr(10) not in details[1:]
    assert not any(ch in details for ch in tricks)


def test_an_argument_name_is_cleaned_and_capped_like_its_value():
    tricks = "".join(chr(c) for c in (0x202E, 0x2028, 0x200B))
    details = ds._call_details({"to" + tricks + "x" * 500: "v"})
    assert not any(ch in details for ch in tricks)
    assert len(details) < ds._CARD_KEY_MAX + 40
