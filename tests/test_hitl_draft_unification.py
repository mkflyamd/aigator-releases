"""Tests for the HITL draft-unification work (issue #52, branch feature/hitl-draft-unification).

Covers Phases 1-4:
  Phase 1 — slack-schedule dead code removed; sendLabel exists on draft types.
  Phase 2 — POST /api/drafts/{id}/open-in-outlook creates a Graph draft and
             returns an OWA URL; unsupported types are rejected.
  Phase 3 — approve_draft attaches navigate_to hints for all messaging types.
  Phase 4 — jira_open_create_form returns _draft (not _pane); approve_draft
             creates the Jira issue, verifies parent/assignee, returns issue_key
             and navigate_to.

Phase 5 (card rendering) is visual-only and requires a running instance.
"""
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).parent.parent / "web"))

from unittest.mock import MagicMock, patch, call

import pytest
from fastapi.testclient import TestClient

from app import app
from skills import _drafts


def _csrf():
    from security import get_csrf_token
    return get_csrf_token()


def _approve(client, draft_id, body=None):
    return client.post(
        f"/api/drafts/{draft_id}/approve",
        headers={"X-CSRF-Token": _csrf()},
        json=body,
    )


def _open_in_outlook(client, draft_id):
    return client.post(
        f"/api/drafts/{draft_id}/open-in-outlook",
        headers={"X-CSRF-Token": _csrf()},
    )


def setup_function(function):
    _drafts._pending_drafts.clear()


# ---------------------------------------------------------------------------
# Phase 1 — slack-schedule dead code removed
# ---------------------------------------------------------------------------

class TestSlackScheduleRemoved:
    """slack-schedule was a dead draft type whose delivery path was already
    deleted. Attempting to approve one must now return 400 (unknown type),
    not ImportError or 500."""

    def test_approve_slack_schedule_returns_400(self):
        client = TestClient(app)
        did = _drafts.create_draft(
            "slack-schedule",
            {"channel_id": "C123", "message": "hello", "post_at": 9999999999},
            {},
        )
        r = _approve(client, did)
        assert r.status_code == 400, r.text
        assert "Unknown draft type" in r.json().get("detail", "")

    def test_slack_schedule_draft_survives_rejection_for_retry(self):
        """A rejected approve must leave the draft in pending so the user
        can retry — same contract as any other failed delivery."""
        client = TestClient(app)
        did = _drafts.create_draft(
            "slack-schedule",
            {"channel_id": "C123", "message": "hello", "post_at": 9999999999},
            {},
        )
        _approve(client, did)
        # Draft must still be retrievable (mark_status pending on failure).
        assert _drafts.get_draft(did) is not None


# ---------------------------------------------------------------------------
# Phase 2 — open-in-outlook endpoint
# ---------------------------------------------------------------------------

def _gc_for_open():
    """Graph client mock for open-in-outlook: POST creates a draft, GET returns body."""
    gc = MagicMock()
    gc.post.return_value = {"id": "NEWDRAFTID123"}
    gc.get.return_value = {"body": {"content": "<p>quoted</p>"}}
    return gc


class TestOpenInOutlook:
    def test_email_send_creates_graph_draft_and_returns_owa_url(self):
        client = TestClient(app)
        gc = _gc_for_open()
        did = _drafts.create_draft(
            "email-send",
            {"to": "bob@amd.com", "subject": "Hello", "body": "Draft body."},
            {},
        )
        with patch("skills._m365.helpers.get_graph_client", return_value=gc):
            r = _open_in_outlook(client, did)
        assert r.status_code == 200, r.text
        url = r.json()["url"]
        assert "outlook.office.com/mail/drafts/id/" in url
        assert "NEWDRAFTID123" in url
        # POST /me/messages (create draft), NOT /me/sendMail
        post_paths = [c.args[0] for c in gc.post.call_args_list]
        assert "/me/messages" in post_paths
        assert not any("sendMail" in p for p in post_paths), \
            "open-in-outlook must NOT send — draft only"

    def test_email_send_gator_draft_survives_open_in_outlook(self):
        """The Gator draft must remain in _pending_drafts after open-in-outlook
        so the user can still approve-and-send from Gator if they prefer."""
        client = TestClient(app)
        gc = _gc_for_open()
        did = _drafts.create_draft(
            "email-send",
            {"to": "bob@amd.com", "subject": "Hello", "body": "body"},
            {},
        )
        with patch("skills._m365.helpers.get_graph_client", return_value=gc):
            _open_in_outlook(client, did)
        assert _drafts.get_draft(did) is not None, \
            "Gator draft must survive open-in-outlook (user may still approve from Gator)"

    def test_email_reply_creates_reply_draft(self):
        client = TestClient(app)
        gc = _gc_for_open()
        did = _drafts.create_draft(
            "email-reply",
            {"message_id": "MSG1", "body": "My reply.", "reply_all": False},
            {},
        )
        with patch("skills._m365.helpers.get_graph_client", return_value=gc):
            r = _open_in_outlook(client, did)
        assert r.status_code == 200, r.text
        # createReply must be called, not /me/messages directly
        post_paths = [c.args[0] for c in gc.post.call_args_list]
        assert any("createReply" in p for p in post_paths)

    def test_email_forward_creates_forward_draft(self):
        client = TestClient(app)
        gc = _gc_for_open()
        did = _drafts.create_draft(
            "email-forward",
            {"message_id": "MSG1", "to": "carol@amd.com", "comment": "FYI"},
            {},
        )
        with patch("skills._m365.helpers.get_graph_client", return_value=gc):
            r = _open_in_outlook(client, did)
        assert r.status_code == 200, r.text
        post_paths = [c.args[0] for c in gc.post.call_args_list]
        assert any("createForward" in p for p in post_paths)

    def test_unknown_draft_id_returns_404(self):
        client = TestClient(app)
        r = _open_in_outlook(client, "nonexistent-draft-id")
        assert r.status_code == 404, r.text

    def test_unsupported_draft_type_returns_400(self):
        client = TestClient(app)
        did = _drafts.create_draft(
            "slack-post",
            {"channel_id": "C123", "message": "hi"},
            {},
        )
        r = _open_in_outlook(client, did)
        assert r.status_code == 400, r.text

    def test_csrf_required(self):
        client = TestClient(app)
        did = _drafts.create_draft(
            "email-send",
            {"to": "bob@amd.com", "subject": "x", "body": "y"},
            {},
        )
        r = client.post(f"/api/drafts/{did}/open-in-outlook")
        assert r.status_code in (401, 403), r.text


# ---------------------------------------------------------------------------
# Phase 3 — navigate_to in approve_draft responses
# ---------------------------------------------------------------------------

class TestNavigateTo:
    """approve_draft must attach navigate_to hints so the frontend can switch
    to the relevant native app after a successful send."""

    def _slack_api(self):
        m = MagicMock()
        m.return_value = {"ok": True, "ts": "123.456"}
        return m

    def test_email_send_navigate_to_outlook(self):
        client = TestClient(app)
        gc = MagicMock()
        gc.post.return_value = {}
        did = _drafts.create_draft(
            "email-send",
            {"to": "bob@amd.com", "subject": "x", "body": "y"},
            {},
        )
        with patch("skills._m365.helpers.get_graph_client", return_value=gc):
            r = _approve(client, did)
        assert r.status_code == 200, r.text
        nav = r.json().get("navigate_to", {})
        assert nav.get("app") == "outlook"

    def test_email_reply_navigate_to_outlook(self):
        client = TestClient(app)
        gc = MagicMock()
        gc.get.return_value = {"id": "MSG1"}
        gc.post.return_value = {"id": "DRAFT1"}
        gc.patch.return_value = {}
        did = _drafts.create_draft(
            "email-reply",
            {"message_id": "MSG1", "body": "reply", "reply_all": False},
            {},
        )
        with patch("skills._m365.helpers.get_graph_client", return_value=gc):
            r = _approve(client, did)
        assert r.status_code == 200, r.text
        assert r.json().get("navigate_to", {}).get("app") == "outlook"

    def test_slack_post_navigate_to_slack_with_channel_id(self):
        from routes.slack import _slack_web_api
        client = TestClient(app)
        did = _drafts.create_draft(
            "slack-post",
            {"channel_id": "C123ABC", "message": "hi"},
            {},
        )
        with patch("routes.slack._slack_web_api", return_value={"ok": True, "ts": "1.2"}):
            r = _approve(client, did)
        assert r.status_code == 200, r.text
        nav = r.json().get("navigate_to", {})
        assert nav.get("app") == "slack"
        assert nav.get("channel_id") == "C123ABC"

    def test_teams_message_navigate_to_teams_with_chat_id(self):
        client = TestClient(app)
        did = _drafts.create_draft(
            "teams-message",
            {"to": "bob@amd.com", "message": "hi", "chat_id": "19:abc@thread.v2",
             "chat_topic": "", "recipients": [], "mentions": []},
            {},
        )
        from routes.teams import TeamsSendMessageRequest
        with patch("routes.teams.tp_teams_send_message",
                   return_value={"ok": True}) as mock_send:
            r = _approve(client, did)
        assert r.status_code == 200, r.text
        nav = r.json().get("navigate_to", {})
        assert nav.get("app") == "teams"
        assert nav.get("chat_id") == "19:abc@thread.v2"

    def test_calendar_write_has_no_navigate_to(self):
        """Calendar write is an MCP approval — no native app to navigate to."""
        client = TestClient(app)
        did = _drafts.create_draft(
            "calendar-write",
            {"connection_id": "gcal1", "tool": "create_event",
             "arguments": {"summary": "Standup", "start": "2026-09-11T09:00:00Z",
                           "end": "2026-09-11T09:30:00Z"}},
            {},
        )
        mock_client = MagicMock()
        mock_client.call.return_value = "ok"
        fake_conn = {"id": "gcal1", "type": "mcp"}
        with patch("mcp.manager._load_connections", return_value=[fake_conn]), \
             patch("mcp.manager._client_for", return_value=mock_client):
            r = _approve(client, did)
        assert r.status_code == 200, r.text
        assert "navigate_to" not in r.json()


# ---------------------------------------------------------------------------
# Phase 4 — Jira draft approval
# ---------------------------------------------------------------------------

def _jira_gc(issue_key="PROJ-42", parent_key="PROJ-10", assignee_id="acc123"):
    """Mock jira_api that simulates a successful issue creation and verification."""
    created = {"key": issue_key}
    verified = {
        "fields": {
            "summary": "Test issue",
            "parent": {"key": parent_key},
            "assignee": {"accountId": assignee_id},
        }
    }

    def _api(method, path, body=None):
        if method == "POST" and path == "issue":
            return created
        if method == "GET" and path.startswith(f"issue/{issue_key}"):
            return verified
        if method == "GET" and path.startswith("issue/PROJ-10"):
            return {"fields": {"summary": "Auth improvements epic"}}
        return {}

    return _api


class TestJiraOpenCreateFormReturnsDraft:
    """jira_open_create_form must return _draft (not _pane) and store the
    issue params in _pending_drafts for the approve_draft handler."""

    def test_returns_draft_signal_not_pane(self):
        from skills.jira.tools import _tool_jira_open_create_form
        with patch("skills.jira.tools.jira_api", side_effect=_jira_gc()), \
             patch("skills.jira.tools._tool_jira_get_project_meta",
                   return_value={"issue_types": []}), \
             patch("skills.jira.tools.jira_is_cloud", return_value=True):
            result = _tool_jira_open_create_form(
                project="PROJ",
                summary="Fix login timeout",
                issue_type="Task",
                parent_key="PROJ-10",
                assignee_account_id="acc123",
                assignee_display="John Smith",
            )
        assert result.get("_draft") == "jira-create", \
            "must return _draft not _pane"
        assert "_pane" not in result, \
            "legacy _pane signal must not be present"

    def test_draft_stored_in_pending_drafts(self):
        from skills.jira.tools import _tool_jira_open_create_form
        with patch("skills.jira.tools.jira_api", side_effect=_jira_gc()), \
             patch("skills.jira.tools._tool_jira_get_project_meta",
                   return_value={"issue_types": []}), \
             patch("skills.jira.tools.jira_is_cloud", return_value=True):
            result = _tool_jira_open_create_form(
                project="PROJ", summary="Fix login", issue_type="Task",
            )
        draft_id = result["data"]["draft_id"]
        draft = _drafts.get_draft(draft_id)
        assert draft is not None
        assert draft["type"] == "jira-create"
        assert draft["params"]["project"] == "PROJ"
        assert draft["params"]["summary"] == "Fix login"

    def test_parent_key_and_assignee_stored_in_params(self):
        from skills.jira.tools import _tool_jira_open_create_form
        with patch("skills.jira.tools.jira_api", side_effect=_jira_gc()), \
             patch("skills.jira.tools._tool_jira_get_project_meta",
                   return_value={"issue_types": []}), \
             patch("skills.jira.tools.jira_is_cloud", return_value=True):
            result = _tool_jira_open_create_form(
                project="PROJ", summary="Fix login", issue_type="Task",
                parent_key="PROJ-10", assignee_account_id="acc123",
            )
        params = _drafts.get_draft(result["data"]["draft_id"])["params"]
        assert params["parent_key"] == "PROJ-10"
        assert params["assignee_account_id"] == "acc123"

    def test_parent_summary_resolved_for_display(self):
        from skills.jira.tools import _tool_jira_open_create_form
        with patch("skills.jira.tools.jira_api", side_effect=_jira_gc()), \
             patch("skills.jira.tools._tool_jira_get_project_meta",
                   return_value={"issue_types": []}), \
             patch("skills.jira.tools.jira_is_cloud", return_value=True):
            result = _tool_jira_open_create_form(
                project="PROJ", summary="Fix login", issue_type="Task",
                parent_key="PROJ-10",
            )
        # The data dict passed to the frontend card should include parent_summary
        assert result["data"]["parent_summary"] == "Auth improvements epic"


class TestJiraApprove:
    """approve_draft for jira-create must POST to Jira, verify parent and
    assignee persisted, return issue_key, and include navigate_to."""

    def _setup_draft(self, parent_key="PROJ-10", assignee_id="acc123"):
        return _drafts.create_draft(
            "jira-create",
            {
                "project": "PROJ",
                "summary": "Fix login timeout",
                "issue_type": "Task",
                "description": "Users get logged out.",
                "priority": "High",
                "extra_fields": {},
                "parent_key": parent_key,
                "assignee_account_id": assignee_id,
                "is_cloud": True,
            },
            {},
        )

    def test_creates_issue_and_returns_key(self):
        client = TestClient(app)
        did = self._setup_draft()
        with patch("skills.jira.api.jira_api", side_effect=_jira_gc()), \
             patch("skills.jira.tools.jira_api", side_effect=_jira_gc()), \
             patch("skills.jira.api.jira_browse_url", return_value="https://jira.example.com"), \
             patch("skills.jira.api.jira_is_cloud", return_value=True):
            r = _approve(client, did)
        assert r.status_code == 200, r.text
        body = r.json()
        assert body.get("issue_key") == "PROJ-42"
        assert "PROJ-42" in body.get("issue_url", "")

    def test_navigate_to_jira_with_issue_url(self):
        client = TestClient(app)
        did = self._setup_draft()
        with patch("skills.jira.api.jira_api", side_effect=_jira_gc()), \
             patch("skills.jira.tools.jira_api", side_effect=_jira_gc()), \
             patch("skills.jira.api.jira_browse_url", return_value="https://jira.example.com"), \
             patch("skills.jira.api.jira_is_cloud", return_value=True):
            r = _approve(client, did)
        nav = r.json().get("navigate_to", {})
        assert nav.get("app") == "jira"
        assert "PROJ-42" in nav.get("url", "")

    def test_parent_mismatch_reported_as_warning_not_error(self):
        """If the parent field didn't persist, the issue is still created but
        ok is 'partial' and the mismatch is surfaced as a warning — not 500."""
        client = TestClient(app)

        def _api_parent_missing(method, path, body=None):
            if method == "POST":
                return {"key": "PROJ-42"}
            # Verification: parent is absent from created issue
            return {"fields": {"summary": "x", "parent": None, "assignee": None}}

        did = self._setup_draft(parent_key="PROJ-10", assignee_id="")
        with patch("skills.jira.api.jira_api", side_effect=_api_parent_missing), \
             patch("skills.jira.tools.jira_api", side_effect=_api_parent_missing), \
             patch("skills.jira.api.jira_browse_url", return_value="https://jira.example.com"), \
             patch("skills.jira.api.jira_is_cloud", return_value=True):
            r = _approve(client, did)
        assert r.status_code == 200, r.text
        body = r.json()
        assert body.get("ok") == "partial"
        warnings = body.get("warnings", [])
        assert any("PROJ-10" in w for w in warnings), \
            "parent mismatch must be reported in warnings"

    def test_assignee_mismatch_reported_as_warning(self):
        client = TestClient(app)

        def _api_assignee_missing(method, path, body=None):
            if method == "POST":
                return {"key": "PROJ-42"}
            return {"fields": {"summary": "x", "parent": None,
                               "assignee": {"accountId": "different-id"}}}

        did = self._setup_draft(parent_key="", assignee_id="acc123")
        with patch("skills.jira.api.jira_api", side_effect=_api_assignee_missing), \
             patch("skills.jira.tools.jira_api", side_effect=_api_assignee_missing), \
             patch("skills.jira.api.jira_browse_url", return_value="https://jira.example.com"), \
             patch("skills.jira.api.jira_is_cloud", return_value=True):
            r = _approve(client, did)
        assert r.status_code == 200, r.text
        body = r.json()
        assert body.get("ok") == "partial"
        assert any("acc123" in w for w in body.get("warnings", []))

    def test_jira_api_failure_returns_500_and_draft_survives(self):
        """If the Jira API call fails, approve must return 500 and leave the
        draft in pending so the user can retry."""
        client = TestClient(app)
        did = self._setup_draft()

        def _api_boom(method, path, body=None):
            raise RuntimeError("Jira is down")

        with patch("skills.jira.api.jira_api", side_effect=_api_boom), \
             patch("skills.jira.tools.jira_api", side_effect=_api_boom), \
             patch("skills.jira.api.jira_browse_url", return_value="https://jira.example.com"), \
             patch("skills.jira.api.jira_is_cloud", return_value=True):
            r = _approve(client, did)
        assert r.status_code == 500, r.text
        assert _drafts.get_draft(did) is not None, \
            "draft must survive a failed Jira API call so the user can retry"

    def test_draft_consumed_on_success(self):
        """On successful creation the draft must be removed from _pending_drafts."""
        client = TestClient(app)
        did = self._setup_draft()
        with patch("skills.jira.api.jira_api", side_effect=_jira_gc()), \
             patch("skills.jira.tools.jira_api", side_effect=_jira_gc()), \
             patch("skills.jira.api.jira_browse_url", return_value="https://jira.example.com"), \
             patch("skills.jira.api.jira_is_cloud", return_value=True):
            r = _approve(client, did)
        assert r.status_code == 200, r.text
        assert _drafts.get_draft(did) is None, \
            "draft must be consumed after successful Jira issue creation"
