"""Tests for Jira staging-tool adapter dispatch.

Each staging tool must:
  - Call resolve_target_for_context (not resolve_builtin_target) so it sees both adapters.
  - For builtin-rest targets: use jira_api for pre-reads, never rovo_jira_call.
  - For rovo-mcp targets: use rovo_jira_call for pre-reads, never jira_api.
  - For watcher and attachment on rovo-mcp: return explicit unavailable error, never draft.
  - For create on rovo-mcp: proceed to draft with rovo-mcp target stored in params.
"""

import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).parent.parent / "web"))

from unittest.mock import MagicMock, patch

import pytest

from skills import _drafts
from skills.jira.mutations import JiraTarget


def _direct_target():
    return JiraTarget(
        id="builtin:https://jira.example.com",
        base_url="https://jira.example.com",
        adapter="builtin-rest",
        is_cloud=True,
    )


def _rovo_target():
    return JiraTarget(
        id="rovo:conn-1:cloud-1",
        base_url="https://jira.example.com",
        adapter="rovo-mcp",
        is_cloud=True,
        connection_id="conn-1",
        resource_id="cloud-1",
    )


def _patch_resolve(target):
    return patch("skills.jira.tools.resolve_target_for_context", return_value=target)


def _patch_rovo_call(side_effect=None):
    default = {"data": {"fields": {}, "key": "PROJ-1"}}
    return patch(
        "skills.jira.mutations.rovo_jira_call",
        return_value=default if side_effect is None else None,
        side_effect=side_effect,
    )


def setup_function(function):
    _drafts._pending_drafts.clear()


# ── comment staging ─────────────────────────────────────────────────────────

class TestCommentStaging:
    def test_direct_uses_jira_api_not_rovo(self):
        direct_api = MagicMock(return_value={"fields": {}})
        rovo_call = MagicMock(side_effect=AssertionError("rovo must not be called for direct target"))
        with _patch_resolve(_direct_target()), \
             patch("skills.jira.tools.jira_api", direct_api), \
             patch("skills.jira.mutations.rovo_jira_call", rovo_call):
            from skills.jira.tools import _tool_jira_add_comment
            result = _tool_jira_add_comment("PROJ-1", "Good work.")
        assert result.get("_draft") == "jira-comment"
        rovo_call.assert_not_called()

    def test_rovo_uses_rovo_call_not_jira_api(self):
        direct_api = MagicMock(side_effect=AssertionError("jira_api must not be called for rovo target"))
        with _patch_resolve(_rovo_target()), \
             patch("skills.jira.tools.jira_api", direct_api), \
             _patch_rovo_call():
            from skills.jira.tools import _tool_jira_add_comment
            result = _tool_jira_add_comment("PROJ-1", "LGTM.")
        assert result.get("_draft") == "jira-comment"
        direct_api.assert_not_called()

    def test_rovo_draft_stores_rovo_target(self):
        with _patch_resolve(_rovo_target()), _patch_rovo_call():
            from skills.jira.tools import _tool_jira_add_comment
            result = _tool_jira_add_comment("PROJ-1", "Note.")
        draft = _drafts.get_draft(result["data"]["draft_id"])
        assert draft["params"]["jira_target"]["adapter"] == "rovo-mcp"


# ── update staging ───────────────────────────────────────────────────────────

class TestUpdateStaging:
    def test_direct_uses_jira_api(self):
        direct_api = MagicMock(return_value={"fields": {}})
        rovo_call = MagicMock(side_effect=AssertionError("rovo must not be called for direct target"))
        with _patch_resolve(_direct_target()), \
             patch("skills.jira.tools.jira_api", direct_api), \
             patch("skills.jira.mutations.rovo_jira_call", rovo_call):
            from skills.jira.tools import _tool_jira_update_issue
            result = _tool_jira_update_issue("PROJ-1", summary="New summary")
        assert result.get("_draft") == "jira-update"
        rovo_call.assert_not_called()

    def test_rovo_uses_rovo_call_for_pre_read(self):
        direct_api = MagicMock(side_effect=AssertionError("jira_api must not be called for rovo target"))
        with _patch_resolve(_rovo_target()), \
             patch("skills.jira.tools.jira_api", direct_api), \
             _patch_rovo_call():
            from skills.jira.tools import _tool_jira_update_issue
            result = _tool_jira_update_issue("PROJ-1", summary="Rovo update")
        assert result.get("_draft") == "jira-update"
        direct_api.assert_not_called()

    def test_rovo_draft_stores_rovo_target(self):
        with _patch_resolve(_rovo_target()), _patch_rovo_call():
            from skills.jira.tools import _tool_jira_update_issue
            result = _tool_jira_update_issue("PROJ-1", summary="x")
        draft = _drafts.get_draft(result["data"]["draft_id"])
        assert draft["params"]["jira_target"]["adapter"] == "rovo-mcp"


# ── watcher staging ──────────────────────────────────────────────────────────

class TestWatcherStaging:
    def test_direct_creates_draft(self):
        with _patch_resolve(_direct_target()), \
             patch("skills.jira.tools.jira_api", return_value={"fields": {}}):
            from skills.jira.tools import _tool_jira_add_watcher
            result = _tool_jira_add_watcher("PROJ-1", "acc-42")
        assert result.get("_draft") == "jira-watcher"

    def test_rovo_returns_unavailable_not_draft(self):
        rovo_call = MagicMock(side_effect=AssertionError("rovo must not be called for unsupported op"))
        with _patch_resolve(_rovo_target()), \
             patch("skills.jira.mutations.rovo_jira_call", rovo_call):
            from skills.jira.tools import _tool_jira_add_watcher
            result = _tool_jira_add_watcher("PROJ-1", "acc-42")
        assert "_draft" not in result
        assert result.get("unavailable") is True
        assert "not available" in result.get("error", "").lower()
        rovo_call.assert_not_called()


# ── attachment staging ────────────────────────────────────────────────────────

class TestAttachmentStaging:
    def test_direct_creates_draft(self, tmp_path, monkeypatch):
        import skills.jira.mutations as m
        monkeypatch.setattr(m.tempfile, "gettempdir", lambda: str(tmp_path))
        staged = m.stage_attachment("file.txt", b"data", "text/plain")
        with _patch_resolve(_direct_target()), \
             patch("skills.jira.tools.jira_api", return_value={"fields": {}}):
            from skills.jira.tools import _tool_jira_stage_attachment
            result = _tool_jira_stage_attachment("PROJ-1", staged["upload_id"])
        assert result.get("_draft") == "jira-attachment"

    def test_rovo_returns_unavailable_not_draft(self):
        rovo_call = MagicMock(side_effect=AssertionError("rovo must not be called"))
        with _patch_resolve(_rovo_target()), \
             patch("skills.jira.mutations.rovo_jira_call", rovo_call):
            from skills.jira.tools import _tool_jira_stage_attachment
            result = _tool_jira_stage_attachment("PROJ-1", "any-id")
        assert "_draft" not in result
        assert result.get("unavailable") is True
        rovo_call.assert_not_called()

    def test_rovo_teams_attachment_returns_unavailable(self):
        with _patch_resolve(_rovo_target()):
            from skills.jira.tools import _tool_jira_stage_teams_attachment
            result = _tool_jira_stage_teams_attachment("PROJ-1", "chat-1", "msg-1")
        assert result.get("unavailable") is True
        assert "_draft" not in result

    def test_rovo_teams_image_returns_unavailable(self):
        with _patch_resolve(_rovo_target()):
            from skills.jira.tools import _tool_jira_stage_teams_image
            result = _tool_jira_stage_teams_image("PROJ-1", "https://teams.microsoft.com/img.png")
        assert result.get("unavailable") is True
        assert "_draft" not in result


# ── transition staging ────────────────────────────────────────────────────────

class TestTransitionStaging:
    def test_direct_uses_jira_api_to_lookup_transition(self):
        transitions_resp = {"transitions": [{"id": "21", "name": "In Progress", "to": {"name": "In Progress"}}]}
        direct_api = MagicMock(return_value=transitions_resp)
        rovo_call = MagicMock(side_effect=AssertionError("rovo must not be called for direct target"))
        with _patch_resolve(_direct_target()), \
             patch("skills.jira.tools.jira_api", direct_api), \
             patch("skills.jira.mutations.rovo_jira_call", rovo_call):
            from skills.jira.tools import _tool_jira_transition
            result = _tool_jira_transition("PROJ-1", "In Progress")
        assert result.get("_draft") == "jira-transition"
        rovo_call.assert_not_called()
        draft = _drafts.get_draft(result["data"]["draft_id"])
        assert draft["params"]["payload"]["transition"]["id"] == "21"

    def test_rovo_returns_unavailable_not_draft(self):
        """Rovo transition is unsupported: no transition-list API exists in Rovo schema."""
        direct_api = MagicMock(side_effect=AssertionError("jira_api must not be called for rovo target"))
        rovo_call = MagicMock(side_effect=AssertionError("rovo_jira_call must not be called either"))
        with _patch_resolve(_rovo_target()), \
             patch("skills.jira.tools.jira_api", direct_api), \
             patch("skills.jira.mutations.rovo_jira_call", rovo_call):
            from skills.jira.tools import _tool_jira_transition
            result = _tool_jira_transition("PROJ-1", "Done")
        assert "_draft" not in result
        assert result.get("unavailable") is True
        assert "not available" in result.get("error", "").lower()
        direct_api.assert_not_called()
        rovo_call.assert_not_called()


# ── link staging ──────────────────────────────────────────────────────────────

class TestLinkStaging:
    def test_direct_uses_jira_api_for_pre_reads(self):
        direct_api = MagicMock(return_value={"fields": {"issuelinks": []}})
        rovo_call = MagicMock(side_effect=AssertionError("rovo must not be called for direct target"))
        with _patch_resolve(_direct_target()), \
             patch("skills.jira.tools.jira_api", direct_api), \
             patch("skills.jira.mutations.rovo_jira_call", rovo_call):
            from skills.jira.tools import _tool_jira_link_issues
            result = _tool_jira_link_issues("PROJ-1", "OTHER-2", "blocks")
        assert result.get("_draft") == "jira-link"
        rovo_call.assert_not_called()

    def test_rovo_uses_rovo_call_for_pre_read(self):
        direct_api = MagicMock(side_effect=AssertionError("jira_api must not be called for rovo target"))
        with _patch_resolve(_rovo_target()), \
             patch("skills.jira.tools.jira_api", direct_api), \
             _patch_rovo_call():
            from skills.jira.tools import _tool_jira_link_issues
            result = _tool_jira_link_issues("PROJ-1", "OTHER-2", "blocks")
        assert result.get("_draft") == "jira-link"
        direct_api.assert_not_called()

    def test_rovo_draft_stores_rovo_target(self):
        with _patch_resolve(_rovo_target()), _patch_rovo_call():
            from skills.jira.tools import _tool_jira_link_issues
            result = _tool_jira_link_issues("PROJ-1", "OTHER-2", "Relates")
        draft = _drafts.get_draft(result["data"]["draft_id"])
        assert draft["params"]["jira_target"]["adapter"] == "rovo-mcp"


# ── create staging (open_create_form) ─────────────────────────────────────────

def _rovo_create_meta_mock():
    """Side-effect for rovo_jira_call during create staging validation.

    Argument shapes and response structures match the real Rovo MCP schemas
    read from mcp-rovo-mcp cached_tools in config.json.bak.20260812134253:

      getVisibleJiraProjects:          cloudId (injected) + optional searchString
      getJiraProjectIssueTypesMetadata: cloudId (injected) + projectIdOrKey (required)
    """
    def _call(target, operation, arguments):
        if operation == "get_projects":
            # getVisibleJiraProjects: cloudId injected; searchString optional
            assert "projectIdOrKey" not in arguments, \
                "get_projects must not pass projectIdOrKey"
            return {"values": [{"key": "PROJ", "name": "My Project"}, {"key": "OTHER", "name": "Other"}]}
        if operation == "get_issue_types":
            # getJiraProjectIssueTypesMetadata: cloudId injected; projectIdOrKey required
            assert "projectIdOrKey" in arguments, \
                f"get_issue_types must receive projectIdOrKey, got: {arguments}"
            assert "project_key" not in arguments, \
                "must use projectIdOrKey not project_key"
            return {"values": [{"id": "10001", "name": "Story"}, {"id": "10002", "name": "Task"}, {"id": "10003", "name": "Bug"}]}
        if operation == "get_create_meta":
            return {"fields": {}}
        return {}
    return _call


class TestCreateStaging:
    def test_direct_creates_draft_with_direct_target(self):
        with patch("skills.jira.tools.resolve_target_for_context", return_value=_direct_target()), \
             patch("skills.jira.tools._tool_jira_get_project_meta", return_value={"issue_types": []}):
            from skills.jira.tools import _tool_jira_open_create_form
            result = _tool_jira_open_create_form(project="PROJ", summary="New issue", issue_type="Task")
        assert result.get("_draft") == "jira-create"
        draft = _drafts.get_draft(result["data"]["draft_id"])
        assert draft["params"]["jira_target"]["adapter"] == "builtin-rest"
        assert draft["params"]["is_cloud"] is True   # target.is_cloud, not jira_is_cloud()

    def test_rovo_creates_draft_with_rovo_target(self):
        with patch("skills.jira.tools.resolve_target_for_context", return_value=_rovo_target()), \
             _patch_rovo_call(side_effect=_rovo_create_meta_mock()):
            from skills.jira.tools import _tool_jira_open_create_form
            result = _tool_jira_open_create_form(project="PROJ", summary="Rovo story", issue_type="Story")
        assert result.get("_draft") == "jira-create", result
        draft = _drafts.get_draft(result["data"]["draft_id"])
        assert draft["params"]["jira_target"]["adapter"] == "rovo-mcp"
        assert draft["params"]["is_cloud"] is True   # target.is_cloud, not jira_is_cloud()

    def test_rovo_create_does_not_call_jira_api(self):
        direct_api = MagicMock(side_effect=AssertionError("jira_api must not be called for rovo target"))
        with patch("skills.jira.tools.resolve_target_for_context", return_value=_rovo_target()), \
             patch("skills.jira.tools.jira_api", direct_api), \
             _patch_rovo_call(side_effect=_rovo_create_meta_mock()):
            from skills.jira.tools import _tool_jira_open_create_form
            result = _tool_jira_open_create_form(project="PROJ", summary="s", issue_type="Task")
        assert result.get("_draft") == "jira-create", result
        direct_api.assert_not_called()

    def test_rovo_create_validates_project_key(self):
        """Unknown project must fail before staging, not at approval time."""
        with patch("skills.jira.tools.resolve_target_for_context", return_value=_rovo_target()), \
             _patch_rovo_call(side_effect=_rovo_create_meta_mock()):
            from skills.jira.tools import _tool_jira_open_create_form
            result = _tool_jira_open_create_form(project="UNKNOWN", summary="s", issue_type="Task")
        assert "_draft" not in result
        assert "not found" in result.get("error", "").lower()

    def test_rovo_create_validates_issue_type(self):
        """Unknown issue type must fail before staging."""
        with patch("skills.jira.tools.resolve_target_for_context", return_value=_rovo_target()), \
             _patch_rovo_call(side_effect=_rovo_create_meta_mock()):
            from skills.jira.tools import _tool_jira_open_create_form
            result = _tool_jira_open_create_form(project="PROJ", summary="s", issue_type="InvalidType")
        assert "_draft" not in result
        assert "not available" in result.get("error", "").lower()

    def test_rovo_create_uses_target_is_cloud_not_global(self):
        """is_cloud in the staged draft must come from target, not jira_is_cloud()."""
        server_target = MagicMock()
        server_target.is_cloud = False  # Server DC target via Rovo
        server_target.adapter = "rovo-mcp"
        server_target.resource_id = "cloud-1"
        server_target.connection_id = "conn-1"
        server_target.base_url = "https://jira.example.com"
        server_target.id = "rovo:conn-1:cloud-1"
        server_target.to_dict.return_value = {"adapter": "rovo-mcp", "is_cloud": False,
                                               "base_url": "https://jira.example.com",
                                               "id": "rovo:conn-1:cloud-1",
                                               "connection_id": "conn-1", "resource_id": "cloud-1",
                                               "display_name": "", "capabilities": []}
        server_target.public_dict.return_value = {"adapter": "rovo-mcp", "is_cloud": False,
                                                   "base_url": "https://jira.example.com"}
        with patch("skills.jira.tools.resolve_target_for_context", return_value=server_target), \
             patch("skills.jira.tools.jira_is_cloud", return_value=True), \
             _patch_rovo_call(side_effect=_rovo_create_meta_mock()):
            from skills.jira.tools import _tool_jira_open_create_form
            result = _tool_jira_open_create_form(project="PROJ", summary="s", issue_type="Task")
        assert result.get("_draft") == "jira-create", result
        draft = _drafts.get_draft(result["data"]["draft_id"])
        assert draft["params"]["is_cloud"] is False, \
            "must use target.is_cloud=False, not global jira_is_cloud()=True"


# ── allowlist regression: rovo_jira_call operation-map layer ─────────────────
#
# These tests mock only at the MCP client layer (_load_connections, _client_for)
# so rovo_jira_call runs its real body, including the _ROVO_OPERATION_TO_TOOL
# lookup and the cached_tools availability check.  If either mapping is removed
# from _ROVO_OPERATION_TO_TOOL the test fails before any client call is made.

_ROVO_CONN_WITH_META_TOOLS = [{
    "id": "conn-1",
    "enabled": True,
    "cached_tools": [
        # Real tool names from mcp-rovo-mcp cached_tools (https://mcp.atlassian.com/v1/mcp)
        {"name": "getVisibleJiraProjects"},
        {"name": "getJiraProjectIssueTypesMetadata"},
        {"name": "getJiraIssueTypeMetaWithFields"},
        {"name": "createJiraIssue"},
        {"name": "getJiraIssue"},
        {"name": "getAccessibleAtlassianResources"},
    ],
}]

_RESOURCES_PAYLOAD = '{"resources": [{"id": "cloud-1", "url": "https://jira.example.com"}]}'


def _mcp_client_for_meta():
    """MCP client mock whose .call() returns real-schema-matching shapes.

    Schemas sourced from the mcp-rovo-mcp connection in config.json.bak.20260812134253:
      getVisibleJiraProjects:
        required: cloudId (injected by rovo_jira_call)
        optional: searchString, action, startAt, maxResults, expandIssueTypes
      getJiraProjectIssueTypesMetadata:
        required: cloudId (injected), projectIdOrKey
    """
    mc = MagicMock()

    def _call(tool_name, args):
        if tool_name == "getAccessibleAtlassianResources":
            return _RESOURCES_PAYLOAD
        if tool_name == "getVisibleJiraProjects":
            # cloudId injected; may receive searchString; must NOT receive projectIdOrKey
            assert "projectIdOrKey" not in args, \
                "getVisibleJiraProjects must not receive projectIdOrKey"
            import json
            return json.dumps({"values": [{"key": "PROJ", "name": "My Project"}, {"key": "OTHER", "name": "Other"}]})
        if tool_name == "getJiraProjectIssueTypesMetadata":
            # cloudId injected; projectIdOrKey required; must NOT use project_key
            assert "projectIdOrKey" in args, \
                f"getJiraProjectIssueTypesMetadata must receive projectIdOrKey, got: {list(args.keys())}"
            assert "project_key" not in args, \
                "must use projectIdOrKey not project_key (snake_case)"
            import json
            return json.dumps({"values": [{"id": "10001", "name": "Story"}, {"id": "10002", "name": "Task"}]})
        if tool_name == "getJiraIssueTypeMetaWithFields":
            import json
            return json.dumps({"fields": {}})
        if tool_name == "createJiraIssue":
            import json
            return json.dumps({"data": {"key": "PROJ-1"}})
        if tool_name == "getJiraIssue":
            import json
            return json.dumps({"data": {"key": "PROJ-1", "fields": {}}})
        raise AssertionError(f"Unexpected tool call: {tool_name!r} args={args}")

    mc.call.side_effect = _call
    return mc


class TestRovoAllowlistRegression:
    """Verify that get_projects and get_issue_types are in _ROVO_OPERATION_TO_TOOL.

    Each test calls the real rovo_jira_call; only _load_connections and
    _client_for are mocked at the MCP layer.  Removing either mapping from
    _ROVO_OPERATION_TO_TOOL causes rovo_jira_call to raise
    JiraTargetResolutionError('Rovo does not have a verified adapter for ...'),
    which propagates as an error result before any draft is created.
    """

    def _target(self):
        return _rovo_target()

    def test_get_projects_is_in_allowlist(self):
        """rovo_jira_call('get_projects') must resolve to getVisibleJiraProjects.

        Tool name sourced from mcp-rovo-mcp cached_tools in config.json.bak.20260812134253
        (https://mcp.atlassian.com/v1/mcp).
        """
        from skills.jira.mutations import _ROVO_OPERATION_TO_TOOL
        assert "get_projects" in _ROVO_OPERATION_TO_TOOL, \
            "'get_projects' must be in _ROVO_OPERATION_TO_TOOL"
        assert _ROVO_OPERATION_TO_TOOL["get_projects"] == "getVisibleJiraProjects", \
            "must map to getVisibleJiraProjects (real Rovo tool name)"

    def test_get_issue_types_is_in_allowlist(self):
        """rovo_jira_call('get_issue_types') must resolve to getJiraProjectIssueTypesMetadata.

        Tool name sourced from mcp-rovo-mcp cached_tools in config.json.bak.20260812134253.
        """
        from skills.jira.mutations import _ROVO_OPERATION_TO_TOOL
        assert "get_issue_types" in _ROVO_OPERATION_TO_TOOL, \
            "'get_issue_types' must be in _ROVO_OPERATION_TO_TOOL"
        assert _ROVO_OPERATION_TO_TOOL["get_issue_types"] == "getJiraProjectIssueTypesMetadata", \
            "must map to getJiraProjectIssueTypesMetadata (real Rovo tool name)"

    def test_create_staging_passes_through_real_allowlist(self):
        """End-to-end: create staging goes through rovo_jira_call's real operation
        map. If either mapping is absent the call raises before returning a draft."""
        with patch("skills.jira.tools.resolve_target_for_context", return_value=self._target()), \
             patch("mcp.manager._load_connections", return_value=_ROVO_CONN_WITH_META_TOOLS), \
             patch("mcp.manager._client_for", return_value=_mcp_client_for_meta()):
            from skills.jira.tools import _tool_jira_open_create_form
            result = _tool_jira_open_create_form(
                project="PROJ", summary="Regression check", issue_type="Story"
            )
        assert result.get("_draft") == "jira-create", (
            f"Expected draft but got: {result}. "
            "If this fails with 'verified adapter' the operation is missing from _ROVO_OPERATION_TO_TOOL."
        )
        draft = _drafts.get_draft(result["data"]["draft_id"])
        assert draft["params"]["jira_target"]["adapter"] == "rovo-mcp"

    def test_create_staging_fails_on_unknown_project_through_real_allowlist(self):
        """Unknown project should fail closed via the real rovo_jira_call path."""
        with patch("skills.jira.tools.resolve_target_for_context", return_value=self._target()), \
             patch("mcp.manager._load_connections", return_value=_ROVO_CONN_WITH_META_TOOLS), \
             patch("mcp.manager._client_for", return_value=_mcp_client_for_meta()):
            from skills.jira.tools import _tool_jira_open_create_form
            result = _tool_jira_open_create_form(
                project="DOES_NOT_EXIST", summary="x", issue_type="Task"
            )
        assert "_draft" not in result
        assert "not found" in result.get("error", "").lower()

    def test_create_staging_fails_on_unknown_issue_type_through_real_allowlist(self):
        """Unknown issue type should fail closed via the real rovo_jira_call path."""
        with patch("skills.jira.tools.resolve_target_for_context", return_value=self._target()), \
             patch("mcp.manager._load_connections", return_value=_ROVO_CONN_WITH_META_TOOLS), \
             patch("mcp.manager._client_for", return_value=_mcp_client_for_meta()):
            from skills.jira.tools import _tool_jira_open_create_form
            result = _tool_jira_open_create_form(
                project="PROJ", summary="x", issue_type="InvalidType"
            )
        assert "_draft" not in result
        assert "not available" in result.get("error", "").lower()
