"""Tests for Jira draft approval via /api/drafts/{id}/approve in routes/drafts.py.

Covers:
  - Direct (builtin-rest): patch jira_api_for_target — not the global jira_api.
  - Rovo (rovo-mcp): assert exact argument schemas sent to rovo_jira_call.
  - Rovo watcher and attachment explicitly refused, no MCP call attempted.
  - No-fallback: direct target never calls rovo_jira_call; Rovo never calls jira_api_for_target.
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
    return get_csrf_token()


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


def _rovo_target():
    return JiraTarget(
        id="rovo:conn-1:cloud-1",
        base_url="https://jira.example.com",
        adapter="rovo-mcp",
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


# ── Rovo transport helpers ──────────────────────────────────────────────────

_ROVO_CONN = [{"id": "conn-1", "enabled": True, "cached_tools": [
    {"name": "createJiraIssue"},
    {"name": "editJiraIssue"},
    {"name": "getJiraIssue"},
    {"name": "addCommentToJiraIssue"},
    {"name": "transitionJiraIssue"},
    {"name": "createIssueLink"},
    {"name": "getAccessibleAtlassianResources"},
]}]

_ROVO_RESOURCES = '{"resources": [{"id": "cloud-1", "url": "https://jira.example.com"}]}'

_ROVO_ISSUE = {
    "key": "PROJ-1",
    "fields": {
        "summary": "Rovo issue",
        "status": {"name": "In Progress"},
        "comment": {"comments": [{"id": "rc1"}]},
        "issuelinks": [{"id": "rlnk1", "type": {"name": "blocks"},
                        "outwardIssue": {"key": "OTHER-2"}}],
    },
}


def _rovo_mcp_client(per_op=None):
    """Return a mock MCP client whose .call() returns resources or per-op data."""
    mc = MagicMock()

    def _call(op, args):
        if op == "getAccessibleAtlassianResources":
            return _ROVO_RESOURCES
        if per_op and op in per_op:
            return per_op[op]
        import json
        return json.dumps({"data": _ROVO_ISSUE})

    mc.call.side_effect = _call
    return mc


class _rovo_patches:
    """Combined context manager: patches load_config + _load_connections for Rovo target revalidation."""

    def __init__(self, extra_conn_tools=None):
        conn = list(_ROVO_CONN)
        if extra_conn_tools:
            conn[0] = dict(conn[0], cached_tools=conn[0]["cached_tools"] + extra_conn_tools)
        self._stack = ExitStack()
        self._patches = [
            patch("skills.jira.mutations.load_config",
                  return_value={"jira_targets": [_target_dict(_rovo_target())]}),
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


# ── jira-create Rovo — exact argument assertions ───────────────────────────

class TestJiraCreateRovo:
    def _draft(self, parent_key="", assignee_id=""):
        return _drafts.create_draft(
            "jira-create",
            {
                "project": "PROJ", "summary": "Rovo story", "issue_type": "Story",
                "description": "A description", "priority": "", "extra_fields": {},
                "parent_key": parent_key, "assignee_account_id": assignee_id,
                "jira_target": _target_dict(_rovo_target()),
            },
            {},
        )

    def _run(self, did, rovo_mock):
        client = TestClient(app)
        with patch("mcp.manager._client_for", return_value=_rovo_mcp_client()), \
             _rovo_patches(), \
             patch("skills.jira.mutations.rovo_jira_call", side_effect=rovo_mock):
            return _approve(client, did)

    def test_creates_and_returns_key(self):
        calls = []

        def mock_rovo(target, operation, arguments):
            calls.append((operation, dict(arguments)))
            if operation == "create_issue":
                return {"data": {"key": "PROJ-1"}}
            return {"data": _ROVO_ISSUE}

        did = self._draft()
        r = self._run(did, mock_rovo)
        assert r.status_code == 200, r.text
        assert r.json()["issue_key"] == "PROJ-1"

    def test_create_args_use_projectKey_issueTypeName_summary(self):
        """rovo_jira_call for create_issue must use the schema field names."""
        calls = []

        def mock_rovo(target, operation, arguments):
            calls.append((operation, dict(arguments)))
            if operation == "create_issue":
                return {"data": {"key": "PROJ-1"}}
            return {"data": _ROVO_ISSUE}

        did = self._draft()
        self._run(did, mock_rovo)
        create_call = next(a for op, a in calls if op == "create_issue")
        assert create_call["projectKey"] == "PROJ"
        assert create_call["issueTypeName"] == "Story"
        assert create_call["summary"] == "Rovo story"
        assert create_call["description"] == "A description"
        assert create_call.get("contentFormat") == "markdown"
        assert "cloudId" not in create_call  # injected by rovo_jira_call, not here

    def test_create_args_include_parent_and_assignee(self):
        calls = []

        def mock_rovo(target, operation, arguments):
            calls.append((operation, dict(arguments)))
            if operation == "create_issue":
                return {"data": {"key": "PROJ-1"}}
            return {"data": _ROVO_ISSUE}

        did = self._draft(parent_key="PROJ-10", assignee_id="acc-xyz")
        self._run(did, mock_rovo)
        create_call = next(a for op, a in calls if op == "create_issue")
        assert create_call.get("parent") == "PROJ-10"
        assert create_call.get("assignee_account_id") == "acc-xyz"

    def test_rovo_create_does_not_call_direct_api(self):
        direct = MagicMock(side_effect=AssertionError("jira_api_for_target must not be called for Rovo target"))
        calls = []

        def mock_rovo(target, operation, arguments):
            calls.append(operation)
            if operation == "create_issue":
                return {"data": {"key": "PROJ-1"}}
            return {"data": _ROVO_ISSUE}

        client = TestClient(app)
        did = self._draft()
        with patch("skills.jira.api.jira_api_for_target", direct), \
             patch("mcp.manager._client_for", return_value=_rovo_mcp_client()), \
             _rovo_patches(), \
             patch("skills.jira.mutations.rovo_jira_call", side_effect=mock_rovo):
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


# ── jira-update Rovo — exact argument assertions ───────────────────────────

class TestJiraUpdateRovo:
    def _draft(self):
        return _drafts.create_draft(
            "jira-update",
            {
                "issue_key": "PROJ-1",
                "fields": {"summary": "Rovo update"},
                "jira_target": _target_dict(_rovo_target()),
            },
            {},
        )

    def test_update_uses_issueIdOrKey_and_fields(self):
        calls = []

        def mock_rovo(target, operation, arguments):
            calls.append((operation, dict(arguments)))
            return {"data": _ROVO_ISSUE}

        client = TestClient(app)
        did = self._draft()
        with patch("mcp.manager._client_for", return_value=_rovo_mcp_client()), \
             _rovo_patches(), \
             patch("skills.jira.mutations.rovo_jira_call", side_effect=mock_rovo):
            r = _approve(client, did)
        assert r.status_code == 200, r.text
        update_call = next(a for op, a in calls if op == "update_issue")
        assert update_call["issueIdOrKey"] == "PROJ-1"
        assert update_call["fields"] == {"summary": "Rovo update"}


# ── jira-watcher: direct ok, Rovo refused ─────────────────────────────────

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

    def test_rovo_watcher_explicitly_refused(self):
        client = TestClient(app)
        did = self._draft(_rovo_target())
        _rovo_conn = [{"id": "conn-1", "enabled": True, "cached_tools": []}]
        with patch("skills.jira.mutations.load_config",
                   return_value={"jira_targets": [_target_dict(_rovo_target())]}), \
             patch("mcp.manager._load_connections", return_value=_rovo_conn):
            r = _approve(client, did)
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["ok"] is False
        assert "not available" in body["error"].lower()
        assert body["verified"]["unavailable"] is True

    def test_rovo_watcher_does_not_call_rovo_api(self):
        client = TestClient(app)
        did = self._draft(_rovo_target())
        rovo_call = MagicMock(side_effect=AssertionError("rovo_jira_call must not fire for watcher"))
        _rovo_conn = [{"id": "conn-1", "enabled": True, "cached_tools": []}]
        with patch("skills.jira.mutations.load_config",
                   return_value={"jira_targets": [_target_dict(_rovo_target())]}), \
             patch("mcp.manager._load_connections", return_value=_rovo_conn), \
             patch("skills.jira.mutations.rovo_jira_call", rovo_call):
            r = _approve(client, did)
        assert r.status_code == 200
        rovo_call.assert_not_called()


# ── jira-attachment: direct ok, Rovo refused ──────────────────────────────

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

    def test_rovo_attachment_explicitly_refused(self):
        client = TestClient(app)
        did = self._draft(_rovo_target())
        _rovo_conn = [{"id": "conn-1", "enabled": True, "cached_tools": []}]
        with patch("skills.jira.mutations.load_config",
                   return_value={"jira_targets": [_target_dict(_rovo_target())]}), \
             patch("mcp.manager._load_connections", return_value=_rovo_conn):
            r = _approve(client, did)
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["ok"] is False
        assert "not available" in body["error"].lower()
        assert body["verified"]["unavailable"] is True

    def test_rovo_attachment_does_not_attempt_upload(self):
        client = TestClient(app)
        did = self._draft(_rovo_target())
        upload_fn = MagicMock(side_effect=AssertionError("upload must not be called for Rovo"))
        _rovo_conn = [{"id": "conn-1", "enabled": True, "cached_tools": []}]
        with patch("skills.jira.mutations.load_config",
                   return_value={"jira_targets": [_target_dict(_rovo_target())]}), \
             patch("mcp.manager._load_connections", return_value=_rovo_conn), \
             patch("skills.jira.api.jira_upload_attachment_for_target", upload_fn):
            r = _approve(client, did)
        assert r.status_code == 200
        upload_fn.assert_not_called()


# ── jira-comment: both branches — exact Rovo args ─────────────────────────

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

    def test_rovo_comment_uses_commentBody_and_contentFormat(self):
        """Rovo commentBody/contentFormat must match the actual Rovo schema."""
        calls = []

        def mock_rovo(target, operation, arguments):
            calls.append((operation, dict(arguments)))
            if operation == "add_comment":
                return {"data": {"id": "rc1"}}
            return {"data": _ROVO_ISSUE}

        client = TestClient(app)
        did = self._draft(_rovo_target())
        with patch("mcp.manager._client_for", return_value=_rovo_mcp_client()), \
             _rovo_patches(), \
             patch("skills.jira.mutations.rovo_jira_call", side_effect=mock_rovo):
            r = _approve(client, did)
        assert r.status_code == 200, r.text

        comment_call = next(a for op, a in calls if op == "add_comment")
        assert comment_call["issueIdOrKey"] == "PROJ-1"
        assert comment_call["commentBody"] == "Looks good."
        assert comment_call["contentFormat"] == "markdown"
        assert "comment" not in comment_call, \
            "must use 'commentBody', not 'comment' (wrong Rovo schema key)"


# ── jira-transition: both branches — exact Rovo args ──────────────────────

class TestJiraTransition:
    def _draft(self, target):
        return _drafts.create_draft(
            "jira-transition",
            {
                "issue_key": "PROJ-1",
                "transition_name": "In Progress",
                "expected_status": "In Progress",
                "payload": {"transition": {"id": "21"}},
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

    def test_rovo_transition_approval_refused_at_409(self):
        """Rovo transition cannot be reached via staging (no transition-list API),
        so any crafted Rovo transition draft must be rejected at approval time."""
        client = TestClient(app)
        did = self._draft(_rovo_target())
        rovo_call = MagicMock(side_effect=AssertionError("rovo_jira_call must not fire"))
        with _rovo_patches(), \
             patch("skills.jira.mutations.rovo_jira_call", rovo_call):
            r = _approve(client, did)
        assert r.status_code == 409, r.text
        assert "not supported" in r.json()["detail"].lower()
        rovo_call.assert_not_called()


# ── jira-link: both branches — exact Rovo args ────────────────────────────

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

    def test_rovo_link_uses_inwardIssue_outwardIssue_type(self):
        """Rovo createIssueLink requires inwardIssue/outwardIssue/type, not the camelCase key variants."""
        calls = []

        def mock_rovo(target, operation, arguments):
            calls.append((operation, dict(arguments)))
            return {"data": _ROVO_ISSUE}

        client = TestClient(app)
        did = self._draft(_rovo_target())
        with patch("mcp.manager._client_for", return_value=_rovo_mcp_client()), \
             _rovo_patches(), \
             patch("skills.jira.mutations.rovo_jira_call", side_effect=mock_rovo):
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

def test_direct_target_does_not_use_rovo_call():
    """builtin-rest approval must use jira_api_for_target, never rovo_jira_call."""
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
    rovo_call = MagicMock(side_effect=AssertionError("rovo_jira_call must not be called for builtin-rest"))
    with patch("skills.jira.mutations.rovo_jira_call", rovo_call), \
         patch("skills.jira.api.jira_browse_url", return_value="https://jira.example.com"), \
         patch("skills.jira.api.jira_api_for_target", side_effect=_direct_api_mock()):
        r = _approve(client, did)
    assert r.status_code == 200
    rovo_call.assert_not_called()


def test_rovo_target_does_not_use_jira_api_for_target():
    """rovo-mcp approval must use rovo_jira_call, never jira_api_for_target."""
    client = TestClient(app)
    did = _drafts.create_draft(
        "jira-create",
        {
            "project": "PROJ", "summary": "s", "issue_type": "Story",
            "description": "", "priority": "", "extra_fields": {},
            "parent_key": "", "assignee_account_id": "",
            "jira_target": _target_dict(_rovo_target()),
        },
        {},
    )
    direct_fn = MagicMock(side_effect=AssertionError("jira_api_for_target must not be called for rovo-mcp"))
    calls = []

    def mock_rovo(target, operation, arguments):
        calls.append(operation)
        if operation == "create_issue":
            return {"data": {"key": "PROJ-1"}}
        return {"data": _ROVO_ISSUE}

    with patch("skills.jira.api.jira_api_for_target", direct_fn), \
         patch("mcp.manager._client_for", return_value=_rovo_mcp_client()), \
         _rovo_patches(), \
         patch("skills.jira.mutations.rovo_jira_call", side_effect=mock_rovo):
        r = _approve(client, did)
    assert r.status_code == 200, r.text
    direct_fn.assert_not_called()
