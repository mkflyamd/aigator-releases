"""Tests for Jira draft approval via /api/drafts/{id}/approve in routes/drafts.py.

Covers:
  - Direct (builtin-rest): patch jira_api_for_target — not the global jira_api.
  - Atlassian MCP (atlassian-mcp): assert exact argument schemas sent to atlassian_mcp_jira_call.
  - Atlassian MCP watcher and attachment explicitly refused, no MCP call attempted.
  - No-fallback: direct target never calls atlassian_mcp_jira_call; Atlassian MCP never calls jira_api_for_target.
  - Duplicate approval rejected; draft consumed on success, preserved on failure.
  - Tab mismatch rejected.
"""

import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).parent.parent / "web"))

from contextlib import ExitStack
from unittest.mock import MagicMock, call, patch

import pytest
from fastapi.testclient import TestClient

from app import app
from skills import _drafts
from skills.jira.mutations import JiraTarget


def _csrf():
    from security import get_csrf_token
    return get_csrf_token("testserver")


def _approve(client, draft_id, body=None):
    return client.post(
        f"/api/drafts/{draft_id}/approve",
        headers={"X-CSRF-Token": _csrf()},
        json=body,
    )


def _direct_target():
    return JiraTarget(
        id="builtin:https://jira.example.com",
        base_url="https://jira.example.com",
        adapter="builtin-rest",
        is_cloud=True,
    )


def _atlassian_mcp_target():
    return JiraTarget(
        id="atlassian-mcp:conn-1:cloud-1",
        base_url="https://jira.example.com",
        adapter="atlassian-mcp",
        is_cloud=True,
        connection_id="conn-1",
        resource_id="cloud-1",
    )


def _target_dict(target: JiraTarget) -> dict:
    return target.to_dict()


def setup_function(function):
    _drafts._pending_drafts.clear()


# ── direct transport helpers ────────────────────────────────────────────────

def _direct_api_mock(issue_key="PROJ-1"):
    """Side-effect for jira_api_for_target. Simulates REST responses by method+path."""
    created = {"key": issue_key}
    issue = {
        "fields": {
            "summary": "Test",
            "status": {"name": "In Progress"},
            "comment": {"comments": [{"id": "c1"}]},
            "issuelinks": [{"id": "lnk1", "type": {"name": "blocks"},
                            "outwardIssue": {"key": "OTHER-2"}}],
        }
    }

    def _api(target, method, path, body=None):
        if method == "POST" and path == "issue":
            return created
        if method == "POST" and "comment" in path:
            return {"id": "c1"}
        if method == "POST" and "transitions" in path:
            return {}
        if method == "POST" and path == "issueLink":
            return {}
        if method in ("PUT", "PATCH"):
            return {}
        if method == "GET":
            return issue
        return {}

    return _api


def _direct_upload_mock():
    return [{"id": "att-1", "filename": "report.pdf", "size": 5}]


# ── Atlassian MCP transport helpers ──────────────────────────────────────────────────

_ATLASSIAN_MCP_CONN = [{"id": "conn-1", "enabled": True, "cached_tools": [
    {"name": "createJiraIssue"},
    {"name": "editJiraIssue"},
    {"name": "getJiraIssue"},
    {"name": "addCommentToJiraIssue"},
    {"name": "transitionJiraIssue"},
    {"name": "createIssueLink"},
    {"name": "getAccessibleAtlassianResources"},
]}]

_ATLASSIAN_MCP_RESOURCES = '{"resources": [{"id": "cloud-1", "url": "https://jira.example.com"}]}'

_ATLASSIAN_MCP_ISSUE = {
    "key": "PROJ-1",
    "fields": {
        "summary": "Atlassian MCP issue",
        "status": {"name": "In Progress"},
        "comment": {"comments": [{"id": "rc1"}]},
        "issuelinks": [{"id": "rlnk1", "type": {"name": "blocks"},
                        "outwardIssue": {"key": "OTHER-2"}}],
    },
}


def _atlassian_mcp_client(per_op=None):
    """Return a mock MCP client whose .call() returns resources or per-op data."""
    mc = MagicMock()

    def _call(op, args):
        if op == "getAccessibleAtlassianResources":
            return _ATLASSIAN_MCP_RESOURCES
        if per_op and op in per_op:
            return per_op[op]
        import json
        return json.dumps({"data": _ATLASSIAN_MCP_ISSUE})

    mc.call.side_effect = _call
    return mc


class _atlassian_mcp_patches:
    """Combined context manager: patches load_config + _load_connections for Atlassian MCP target revalidation."""

    def __init__(self, extra_conn_tools=None):
        conn = list(_ATLASSIAN_MCP_CONN)
        if extra_conn_tools:
            conn[0] = dict(conn[0], cached_tools=conn[0]["cached_tools"] + extra_conn_tools)
        self._stack = ExitStack()
        self._patches = [
            patch("skills.jira.mutations.load_config",
                  return_value={"jira_targets": [_target_dict(_atlassian_mcp_target())]}),
            patch("mcp.manager._load_connections", return_value=conn),
        ]

    def __enter__(self):
        for p in self._patches:
            self._stack.enter_context(p)
        return self

    def __exit__(self, *args):
        return self._stack.__exit__(*args)


# ── jira-create direct ─────────────────────────────────────────────────────

class TestJiraCreateDirect:
    def _draft(self):
        return _drafts.create_draft(
            "jira-create",
            {
                "project": "PROJ", "summary": "Fix it", "issue_type": "Task",
                "description": "desc", "priority": "High", "extra_fields": {},
                "parent_key": "", "assignee_account_id": "",
                "jira_target": _target_dict(_direct_target()),
            },
            {},
        )

    def _patches(self):
        return [
            patch("skills.jira.api.jira_api_for_target", side_effect=_direct_api_mock()),
        ]

    def test_creates_and_returns_key(self):
        client = TestClient(app)
        did = self._draft()
        with patch("skills.jira.api.jira_browse_url", return_value="https://jira.example.com"), \
             patch("skills.jira.api.jira_api_for_target", side_effect=_direct_api_mock()):
            r = _approve(client, did)
        assert r.status_code == 200, r.text
        assert r.json()["issue_key"] == "PROJ-1"

    def test_navigate_to_jira(self):
        client = TestClient(app)
        did = self._draft()
        with patch("skills.jira.api.jira_browse_url", return_value="https://jira.example.com"), \
             patch("skills.jira.api.jira_api_for_target", side_effect=_direct_api_mock()):
            r = _approve(client, did)
        assert r.status_code == 200, r.text
        assert r.json()["navigate_to"]["app"] == "jira"

    def test_draft_consumed_on_success(self):
        client = TestClient(app)
        did = self._draft()
        with patch("skills.jira.api.jira_browse_url", return_value="https://jira.example.com"), \
             patch("skills.jira.api.jira_api_for_target", side_effect=_direct_api_mock()):
            _approve(client, did)
        assert _drafts.get_draft(did) is None

    def test_draft_preserved_on_api_failure(self):
        client = TestClient(app)
        did = self._draft()
        with patch("skills.jira.api.jira_browse_url", return_value="https://jira.example.com"), \
             patch("skills.jira.api.jira_api_for_target", side_effect=RuntimeError("Jira down")):
            r = _approve(client, did)
        assert r.status_code == 500
        assert _drafts.get_draft(did) is not None

    def test_tab_mismatch_rejected(self):
        client = TestClient(app)
        did = _drafts.create_draft(
            "jira-create",
            {
                "project": "PROJ", "summary": "Fix it", "issue_type": "Task",
                "description": "desc", "priority": "High", "extra_fields": {},
                "parent_key": "", "assignee_account_id": "",
                "jira_target": _target_dict(_direct_target()),
                "context_id": "tab-RIGHT",
            },
            {},
        )
        r = _approve(client, did, {"context_id": "tab-WRONG"})
        assert r.status_code == 409
        assert "different tab" in r.json()["detail"]

    def test_duplicate_approve_rejected(self):
        client = TestClient(app)
        did = self._draft()
        with patch("skills.jira.api.jira_browse_url", return_value="https://jira.example.com"), \
             patch("skills.jira.api.jira_api_for_target", side_effect=_direct_api_mock()):
            r1 = _approve(client, did)
        assert r1.status_code == 200
        r2 = _approve(client, did)
        assert r2.status_code == 404


# ── jira-create Atlassian MCP — exact argument assertions ───────────────────────────

class TestJiraCreateAtlassianMcp:
    def _draft(self, parent_key="", assignee_id=""):
        return _drafts.create_draft(
            "jira-create",
            {
                "project": "PROJ", "summary": "Atlassian MCP story", "issue_type": "Story",
                "description": "A description", "priority": "", "extra_fields": {},
                "parent_key": parent_key, "assignee_account_id": assignee_id,
                "jira_target": _target_dict(_atlassian_mcp_target()),
            },
            {},
        )

    def _run(self, did, atlassian_mcp_mock):
        client = TestClient(app)
        with patch("mcp.manager._client_for", return_value=_atlassian_mcp_client()), \
             _atlassian_mcp_patches(), \
             patch("skills.jira.mutations.atlassian_mcp_jira_call", side_effect=atlassian_mcp_mock):
            return _approve(client, did)

    def test_creates_and_returns_key(self):
        calls = []

        def mock_atlassian_mcp(target, operation, arguments):
            calls.append((operation, dict(arguments)))
            if operation == "create_issue":
                return {"data": {"key": "PROJ-1"}}
            return {"data": _ATLASSIAN_MCP_ISSUE}

        did = self._draft()
        r = self._run(did, mock_atlassian_mcp)
        assert r.status_code == 200, r.text
        assert r.json()["issue_key"] == "PROJ-1"

    def test_create_args_use_projectKey_issueTypeName_summary(self):
        """atlassian_mcp_jira_call for create_issue must use the schema field names."""
        calls = []

        def mock_atlassian_mcp(target, operation, arguments):
            calls.append((operation, dict(arguments)))
            if operation == "create_issue":
                return {"data": {"key": "PROJ-1"}}
            return {"data": _ATLASSIAN_MCP_ISSUE}

        did = self._draft()
        self._run(did, mock_atlassian_mcp)
        create_call = next(a for op, a in calls if op == "create_issue")
        assert create_call["projectKey"] == "PROJ"
        assert create_call["issueTypeName"] == "Story"
        assert create_call["summary"] == "Atlassian MCP story"
        assert create_call["description"] == "A description"
        assert create_call.get("contentFormat") == "markdown"
        assert "cloudId" not in create_call  # injected by atlassian_mcp_jira_call, not here

    def test_create_args_include_parent_and_assignee(self):
        calls = []

        def mock_atlassian_mcp(target, operation, arguments):
            calls.append((operation, dict(arguments)))
            if operation == "create_issue":
                return {"data": {"key": "PROJ-1"}}
            return {"data": _ATLASSIAN_MCP_ISSUE}

        did = self._draft(parent_key="PROJ-10", assignee_id="acc-xyz")
        self._run(did, mock_atlassian_mcp)
        create_call = next(a for op, a in calls if op == "create_issue")
        assert create_call.get("parent") == "PROJ-10"
        assert create_call.get("assignee_account_id") == "acc-xyz"

    def test_atlassian_mcp_create_does_not_call_direct_api(self):
        direct = MagicMock(side_effect=AssertionError("jira_api_for_target must not be called for Atlassian MCP target"))
        calls = []

        def mock_atlassian_mcp(target, operation, arguments):
            calls.append(operation)
            if operation == "create_issue":
                return {"data": {"key": "PROJ-1"}}
            return {"data": _ATLASSIAN_MCP_ISSUE}

        client = TestClient(app)
        did = self._draft()
        with patch("skills.jira.api.jira_api_for_target", direct), \
             patch("mcp.manager._client_for", return_value=_atlassian_mcp_client()), \
             _atlassian_mcp_patches(), \
             patch("skills.jira.mutations.atlassian_mcp_jira_call", side_effect=mock_atlassian_mcp):
            r = _approve(client, did)
        assert r.status_code == 200, r.text
        direct.assert_not_called()


# ── jira-update direct ─────────────────────────────────────────────────────

class TestJiraUpdateDirect:
    def _draft(self, fields=None):
        return _drafts.create_draft(
            "jira-update",
            {
                "issue_key": "PROJ-1",
                "fields": fields or {"summary": "Updated"},
                "jira_target": _target_dict(_direct_target()),
            },
            {},
        )

    def test_update_verified(self):
        client = TestClient(app)
        did = self._draft()
        with patch("skills.jira.api.jira_browse_url", return_value="https://jira.example.com"), \
             patch("skills.jira.api.jira_api_for_target", side_effect=_direct_api_mock()):
            r = _approve(client, did)
        assert r.status_code == 200, r.text
        assert r.json()["issue_key"] == "PROJ-1"

    def test_update_partial_when_field_not_persisted(self):
        client = TestClient(app)
        did = self._draft(fields={"priority": {"name": "Blocker"}})

        def _api(target, method, path, body=None):
            if method == "GET":
                return {"fields": {"priority": {"name": "High"}}}
            return {}

        with patch("skills.jira.api.jira_browse_url", return_value="https://jira.example.com"), \
             patch("skills.jira.api.jira_api_for_target", side_effect=_api):
            r = _approve(client, did)
        assert r.status_code == 200
        assert r.json()["ok"] == "partial"


# ── jira-update Atlassian MCP — exact argument assertions ───────────────────────────

class TestJiraUpdateAtlassianMcp:
    def _draft(self):
        return _drafts.create_draft(
            "jira-update",
            {
                "issue_key": "PROJ-1",
                "fields": {"summary": "Atlassian MCP update"},
                "jira_target": _target_dict(_atlassian_mcp_target()),
            },
            {},
        )

    def test_update_uses_issueIdOrKey_and_fields(self):
        calls = []

        def mock_atlassian_mcp(target, operation, arguments):
            calls.append((operation, dict(arguments)))
            return {"data": _ATLASSIAN_MCP_ISSUE}

        client = TestClient(app)
        did = self._draft()
        with patch("mcp.manager._client_for", return_value=_atlassian_mcp_client()), \
             _atlassian_mcp_patches(), \
             patch("skills.jira.mutations.atlassian_mcp_jira_call", side_effect=mock_atlassian_mcp):
            r = _approve(client, did)
        assert r.status_code == 200, r.text
        update_call = next(a for op, a in calls if op == "update_issue")
        assert update_call["issueIdOrKey"] == "PROJ-1"
        assert update_call["fields"] == {"summary": "Atlassian MCP update"}


# ── jira-watcher: direct ok, Atlassian MCP refused ─────────────────────────────────

class TestJiraWatcher:
    def _draft(self, target):
        return _drafts.create_draft(
            "jira-watcher",
            {
                "issue_key": "PROJ-1", "account_id": "acc-42",
                "jira_target": _target_dict(target),
            },
            {},
        )

    def test_direct_watcher_verified(self):
        client = TestClient(app)
        did = self._draft(_direct_target())
        watchers_resp = {"watchers": [{"accountId": "acc-42"}]}

        def _api(target, method, path, body=None):
            if "watchers" in path and method == "GET":
                return watchers_resp
            return {}

        with patch("skills.jira.api.jira_browse_url", return_value="https://jira.example.com"), \
             patch("skills.jira.api.jira_api_for_target", side_effect=_api):
            r = _approve(client, did)
        assert r.status_code == 200, r.text
        assert r.json()["verified"]["watcher_present"] is True

    def test_atlassian_mcp_watcher_explicitly_refused(self):
        client = TestClient(app)
        did = self._draft(_atlassian_mcp_target())
        _atlassian_mcp_conn = [{"id": "conn-1", "enabled": True, "cached_tools": []}]
        with patch("skills.jira.mutations.load_config",
                   return_value={"jira_targets": [_target_dict(_atlassian_mcp_target())]}), \
             patch("mcp.manager._load_connections", return_value=_atlassian_mcp_conn):
            r = _approve(client, did)
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["ok"] is False
        assert "not available" in body["error"].lower()
        assert body["verified"]["unavailable"] is True

    def test_atlassian_mcp_watcher_does_not_call_atlassian_mcp_api(self):
        client = TestClient(app)
        did = self._draft(_atlassian_mcp_target())
        atlassian_mcp_call = MagicMock(side_effect=AssertionError("atlassian_mcp_jira_call must not fire for watcher"))
        _atlassian_mcp_conn = [{"id": "conn-1", "enabled": True, "cached_tools": []}]
        with patch("skills.jira.mutations.load_config",
                   return_value={"jira_targets": [_target_dict(_atlassian_mcp_target())]}), \
             patch("mcp.manager._load_connections", return_value=_atlassian_mcp_conn), \
             patch("skills.jira.mutations.atlassian_mcp_jira_call", atlassian_mcp_call):
            r = _approve(client, did)
        assert r.status_code == 200
        atlassian_mcp_call.assert_not_called()


# ── jira-attachment: direct ok, Atlassian MCP refused ──────────────────────────────

class TestJiraAttachment:
    def _draft(self, target, upload_id="uid-1"):
        return _drafts.create_draft(
            "jira-attachment",
            {
                "issue_key": "PROJ-1", "upload_id": upload_id,
                "jira_target": _target_dict(target),
            },
            {},
        )

    def test_direct_attachment_verified(self, tmp_path, monkeypatch):
        import skills.jira.mutations as m
        monkeypatch.setattr(m.tempfile, "gettempdir", lambda: str(tmp_path))
        staged = m.stage_attachment("report.pdf", b"bytes", "application/pdf")
        client = TestClient(app)
        did = self._draft(_direct_target(), staged["upload_id"])
        uploaded = [{"id": "att-1", "filename": "report.pdf", "size": 5}]

        def _api(target, method, path, body=None):
            return {"fields": {}}

        with patch("skills.jira.api.jira_browse_url", return_value="https://jira.example.com"), \
             patch("skills.jira.api.jira_api_for_target", side_effect=_api), \
             patch("skills.jira.api.jira_upload_attachment_for_target",
                   return_value=uploaded):
            r = _approve(client, did)
        assert r.status_code == 200, r.text
        assert r.json()["verified"]["metadata_match"] is True

    def test_atlassian_mcp_attachment_explicitly_refused(self):
        client = TestClient(app)
        did = self._draft(_atlassian_mcp_target())
        _atlassian_mcp_conn = [{"id": "conn-1", "enabled": True, "cached_tools": []}]
        with patch("skills.jira.mutations.load_config",
                   return_value={"jira_targets": [_target_dict(_atlassian_mcp_target())]}), \
             patch("mcp.manager._load_connections", return_value=_atlassian_mcp_conn):
            r = _approve(client, did)
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["ok"] is False
        assert "not available" in body["error"].lower()
        assert body["verified"]["unavailable"] is True

    def test_atlassian_mcp_attachment_does_not_attempt_upload(self):
        client = TestClient(app)
        did = self._draft(_atlassian_mcp_target())
        upload_fn = MagicMock(side_effect=AssertionError("upload must not be called for Atlassian MCP"))
        _atlassian_mcp_conn = [{"id": "conn-1", "enabled": True, "cached_tools": []}]
        with patch("skills.jira.mutations.load_config",
                   return_value={"jira_targets": [_target_dict(_atlassian_mcp_target())]}), \
             patch("mcp.manager._load_connections", return_value=_atlassian_mcp_conn), \
             patch("skills.jira.api.jira_upload_attachment_for_target", upload_fn):
            r = _approve(client, did)
        assert r.status_code == 200
        upload_fn.assert_not_called()


# ── jira-comment: both branches — exact Atlassian MCP args ─────────────────────────

class TestJiraComment:
    def _draft(self, target):
        return _drafts.create_draft(
            "jira-comment",
            {
                "issue_key": "PROJ-1", "comment": "Looks good.",
                "jira_target": _target_dict(target),
            },
            {},
        )

    def test_direct_comment_verified(self):
        client = TestClient(app)
        did = self._draft(_direct_target())
        with patch("skills.jira.api.jira_browse_url", return_value="https://jira.example.com"), \
             patch("skills.jira.api.jira_api_for_target", side_effect=_direct_api_mock()):
            r = _approve(client, did)
        assert r.status_code == 200, r.text
        assert r.json()["verified"]["present"] is True

    def test_atlassian_mcp_comment_uses_commentBody_and_contentFormat(self):
        """Atlassian MCP commentBody/contentFormat must match the actual Atlassian MCP schema."""
        calls = []

        def mock_atlassian_mcp(target, operation, arguments):
            calls.append((operation, dict(arguments)))
            if operation == "add_comment":
                return {"data": {"id": "rc1"}}
            return {"data": _ATLASSIAN_MCP_ISSUE}

        client = TestClient(app)
        did = self._draft(_atlassian_mcp_target())
        with patch("mcp.manager._client_for", return_value=_atlassian_mcp_client()), \
             _atlassian_mcp_patches(), \
             patch("skills.jira.mutations.atlassian_mcp_jira_call", side_effect=mock_atlassian_mcp):
            r = _approve(client, did)
        assert r.status_code == 200, r.text

        comment_call = next(a for op, a in calls if op == "add_comment")
        assert comment_call["issueIdOrKey"] == "PROJ-1"
        assert comment_call["commentBody"] == "Looks good."
        assert comment_call["contentFormat"] == "markdown"
        assert "comment" not in comment_call, \
            "must use 'commentBody', not 'comment' (wrong Atlassian MCP schema key)"


# ── jira-transition: both branches — exact Atlassian MCP args ──────────────────────

class TestJiraTransition:
    def _draft(self, target, payload=None):
        return _drafts.create_draft(
            "jira-transition",
            {
                "issue_key": "PROJ-1",
                "transition_name": "In Progress",
                "expected_status": "In Progress",
                "payload": payload if payload is not None else {"transition": {"id": "21"}},
                "jira_target": _target_dict(target),
            },
            {},
        )

    def test_direct_transition_verified(self):
        client = TestClient(app)
        did = self._draft(_direct_target())
        with patch("skills.jira.api.jira_browse_url", return_value="https://jira.example.com"), \
             patch("skills.jira.api.jira_api_for_target", side_effect=_direct_api_mock()):
            r = _approve(client, did)
        assert r.status_code == 200, r.text
        assert r.json()["verified"]["matched"] is True

    def _approve_atlassian_mcp(self, payload, mock_atlassian_mcp):
        client = TestClient(app)
        did = self._draft(_atlassian_mcp_target(), payload)
        direct_api = MagicMock(side_effect=AssertionError("direct REST must not be used for an Atlassian MCP site"))
        with patch("mcp.manager._client_for", return_value=_atlassian_mcp_client()), \
             _atlassian_mcp_patches(), \
             patch("skills.jira.api.jira_api_for_target", direct_api), \
             patch("skills.jira.mutations.atlassian_mcp_jira_call", side_effect=mock_atlassian_mcp):
            return _approve(client, did)

    def test_atlassian_mcp_transition_runs_by_id_and_is_read_back(self):
        calls = []

        def mock_atlassian_mcp(target, operation, arguments):
            calls.append((operation, dict(arguments)))
            return {"data": _ATLASSIAN_MCP_ISSUE}

        r = self._approve_atlassian_mcp({"transition": {"id": "21"}}, mock_atlassian_mcp)
        assert r.status_code == 200, r.text
        assert [op for op, _ in calls] == ["get_issue", "transition_issue", "get_issue"]
        assert calls[1][1] == {"issueIdOrKey": "PROJ-1", "transitionId": "21"}
        assert r.json()["verified"]["matched"] is True and r.json()["ok"] is True
        assert r.json()["target"]["adapter"] == "atlassian-mcp"

    def test_atlassian_mcp_transition_read_back_that_disagrees_is_partial(self):
        stale = {"data": {"key": "PROJ-1", "fields": {"status": {"name": "Open"}}}}
        r = self._approve_atlassian_mcp(
            {"transition": {"id": "21"}}, lambda target, operation, arguments: stale)
        assert r.status_code == 200, r.text
        assert r.json()["ok"] == "partial" and r.json()["verified"]["matched"] is False

    def test_atlassian_mcp_transition_sends_fields_and_posts_the_comment_separately(self):
        calls = []

        def mock_atlassian_mcp(target, operation, arguments):
            calls.append((operation, dict(arguments)))
            return {"data": _ATLASSIAN_MCP_ISSUE}

        payload = {
            "transition": {"id": "61"},
            "fields": {"customfield_10150": {"value": "Duplicate"}},
            "update": {"comment": [{"add": {"body": "Closing as a dupe."}}]},
        }
        r = self._approve_atlassian_mcp(payload, mock_atlassian_mcp)
        assert r.status_code == 200, r.text
        transition = next(a for op, a in calls if op == "transition_issue")
        assert transition == {
            "issueIdOrKey": "PROJ-1", "transitionId": "61",
            "fields": {"customfield_10150": {"value": "Duplicate"}}}
        comment = next(a for op, a in calls if op == "add_comment")
        assert comment["commentBody"] == "Closing as a dupe." and comment["contentFormat"] == "markdown"

    def test_atlassian_mcp_transition_whose_comment_fails_still_reports_the_status_change(self):
        def mock_atlassian_mcp(target, operation, arguments):
            if operation == "add_comment":
                raise RuntimeError("comment refused")
            return {"data": _ATLASSIAN_MCP_ISSUE}

        payload = {"transition": {"id": "21"}, "update": {"comment": [{"add": {"body": "why"}}]}}
        r = self._approve_atlassian_mcp(payload, mock_atlassian_mcp)
        assert r.status_code == 200, r.text
        assert r.json()["ok"] == "partial" and r.json()["verified"]["matched"] is True
        assert "comment could not be added" in r.json()["warning"]

    def test_atlassian_mcp_transition_draft_without_an_id_is_rejected_before_any_call(self):
        atlassian_mcp_call = MagicMock(side_effect=AssertionError("atlassian_mcp_jira_call must not fire"))
        r = self._approve_atlassian_mcp({"transition": {}}, atlassian_mcp_call)
        assert r.status_code == 400, r.text
        atlassian_mcp_call.assert_not_called()

    def test_atlassian_mcp_transition_that_atlassian_mcp_rejects_is_not_reported_as_done(self):
        def mock_atlassian_mcp(target, operation, arguments):
            if operation == "transition_issue":
                raise RuntimeError("Transition requires field resolution")
            return {"data": _ATLASSIAN_MCP_ISSUE}

        r = self._approve_atlassian_mcp({"transition": {"id": "51"}}, mock_atlassian_mcp)
        assert r.status_code == 502, r.text
        assert "resolution" in r.json()["detail"]


# ── jira-link: both branches — exact Atlassian MCP args ────────────────────────────

class TestJiraLink:
    def _draft(self, target):
        return _drafts.create_draft(
            "jira-link",
            {
                "issue_key": "PROJ-1", "other_key": "OTHER-2", "link_type": "blocks",
                "before_link_ids": [],
                "payload": {
                    "type": {"name": "blocks"},
                    "inwardIssue": {"key": "PROJ-1"},
                    "outwardIssue": {"key": "OTHER-2"},
                },
                "jira_target": _target_dict(target),
            },
            {},
        )

    def test_direct_link_verified(self):
        client = TestClient(app)
        did = self._draft(_direct_target())
        with patch("skills.jira.api.jira_browse_url", return_value="https://jira.example.com"), \
             patch("skills.jira.api.jira_api_for_target", side_effect=_direct_api_mock()):
            r = _approve(client, did)
        assert r.status_code == 200, r.text
        assert r.json()["verified"]["link_present"] is True

    def test_atlassian_mcp_link_uses_inwardIssue_outwardIssue_type(self):
        """Atlassian MCP createIssueLink requires inwardIssue/outwardIssue/type, not the camelCase key variants."""
        calls = []

        def mock_atlassian_mcp(target, operation, arguments):
            calls.append((operation, dict(arguments)))
            return {"data": _ATLASSIAN_MCP_ISSUE}

        client = TestClient(app)
        did = self._draft(_atlassian_mcp_target())
        with patch("mcp.manager._client_for", return_value=_atlassian_mcp_client()), \
             _atlassian_mcp_patches(), \
             patch("skills.jira.mutations.atlassian_mcp_jira_call", side_effect=mock_atlassian_mcp):
            r = _approve(client, did)
        assert r.status_code == 200, r.text

        link_call = next(a for op, a in calls if op == "create_link")
        assert "inwardIssue" in link_call, "must use 'inwardIssue' (not 'inwardIssueKey')"
        assert "outwardIssue" in link_call, "must use 'outwardIssue' (not 'outwardIssueKey')"
        assert "type" in link_call, "must use 'type' (not 'linkType')"
        assert link_call["type"] == "blocks"
        assert "linkType" not in link_call, "wrong key 'linkType' must not be present"
        assert "inwardIssueKey" not in link_call, "wrong key 'inwardIssueKey' must not be present"
        assert "outwardIssueKey" not in link_call, "wrong key 'outwardIssueKey' must not be present"


# ── no-fallback invariants ─────────────────────────────────────────────────

def test_direct_target_does_not_use_atlassian_mcp_call():
    """builtin-rest approval must use jira_api_for_target, never atlassian_mcp_jira_call."""
    client = TestClient(app)
    did = _drafts.create_draft(
        "jira-create",
        {
            "project": "PROJ", "summary": "s", "issue_type": "Task",
            "description": "", "priority": "", "extra_fields": {},
            "parent_key": "", "assignee_account_id": "",
            "jira_target": _target_dict(_direct_target()),
        },
        {},
    )
    atlassian_mcp_call = MagicMock(side_effect=AssertionError("atlassian_mcp_jira_call must not be called for builtin-rest"))
    with patch("skills.jira.mutations.atlassian_mcp_jira_call", atlassian_mcp_call), \
         patch("skills.jira.api.jira_browse_url", return_value="https://jira.example.com"), \
         patch("skills.jira.api.jira_api_for_target", side_effect=_direct_api_mock()):
        r = _approve(client, did)
    assert r.status_code == 200
    atlassian_mcp_call.assert_not_called()


def test_atlassian_mcp_target_does_not_use_jira_api_for_target():
    """atlassian-mcp approval must use atlassian_mcp_jira_call, never jira_api_for_target."""
    client = TestClient(app)
    did = _drafts.create_draft(
        "jira-create",
        {
            "project": "PROJ", "summary": "s", "issue_type": "Story",
            "description": "", "priority": "", "extra_fields": {},
            "parent_key": "", "assignee_account_id": "",
            "jira_target": _target_dict(_atlassian_mcp_target()),
        },
        {},
    )
    direct_fn = MagicMock(side_effect=AssertionError("jira_api_for_target must not be called for atlassian-mcp"))
    calls = []

    def mock_atlassian_mcp(target, operation, arguments):
        calls.append(operation)
        if operation == "create_issue":
            return {"data": {"key": "PROJ-1"}}
        return {"data": _ATLASSIAN_MCP_ISSUE}

    with patch("skills.jira.api.jira_api_for_target", direct_fn), \
         patch("mcp.manager._client_for", return_value=_atlassian_mcp_client()), \
         _atlassian_mcp_patches(), \
         patch("skills.jira.mutations.atlassian_mcp_jira_call", side_effect=mock_atlassian_mcp):
        r = _approve(client, did)
    assert r.status_code == 200, r.text
    direct_fn.assert_not_called()
