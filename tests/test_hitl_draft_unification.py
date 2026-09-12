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

    def test_open_outlook_draft_syncs_native_pane_before_loading_url(self):
        source = (pathlib.Path(__file__).parent.parent / "web" / "static" / "app.js").read_text(
            encoding="utf-8", errors="replace"
        )
        start = source.find("const { url } = await res.json()")
        assert start != -1
        block = source[start : start + 900]
        assert block.find("openThirdPane('email')") < block.find("openOutlookDraft(url)")


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

    def test_new_teams_chat_uses_resolved_chat_id_for_navigation(self):
        """A draft with no pre-existing chat must navigate to the chat created
        by the approved send, rather than silently omitting navigation."""
        client = TestClient(app)
        did = _drafts.create_draft(
            "teams-message",
            {"to": "bob@amd.com", "message": "hi", "chat_id": "", "recipients": [], "mentions": []},
            {},
        )
        with patch(
            "routes.teams.tp_teams_send_message",
            return_value={"sent": True, "chat_id": "19:new@thread.v2", "message_id": "42"},
        ):
            r = _approve(client, did)
        assert r.status_code == 200, r.text
        nav = r.json().get("navigate_to", {})
        assert nav == {"app": "teams", "chat_id": "19:new@thread.v2"}

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


# ---------------------------------------------------------------------------
# Teams and Slack native-app navigation contract
# ---------------------------------------------------------------------------

class TestTeamsAndSlackDraftContract:
    """Teams and Slack do not expose supported server-side draft APIs.

    Their Gator cards remain the editable source of truth. Native-app actions
    are context-only navigation; they must never claim to hand off a draft.
    """

    APP_JS = (pathlib.Path(__file__).parent.parent / "web" / "static" / "app.js").read_text(
        encoding="utf-8", errors="replace"
    )

    def test_teams_tool_emits_draft_not_legacy_pane(self):
        from skills.teams.tools import _tool_teams_open_compose

        result = _tool_teams_open_compose(
            to="person@example.com",
            to_names="Person Example",
            message="Draft text",
            chat_id="19:abc@thread.v2",
        )
        assert result["_draft"] == "teams-message"
        assert "_pane" not in result
        assert result["data"]["draft_id"] in _drafts._pending_drafts

    def test_teams_tool_accepts_known_chat_without_to(self):
        """The public schema permits an omitted recipient when chat_id is
        known. Keep the Python handler aligned with that contract."""
        from skills.teams.tools import _tool_teams_open_compose

        result = _tool_teams_open_compose(
            message="Sounds good. Please ping me when available.",
            chat_id="19:abc@thread.v2",
        )
        assert result["_draft"] == "teams-message"
        assert result["data"]["to"] == ""

    def test_teams_tool_rejects_missing_recipient_and_chat(self):
        from skills.teams.tools import _tool_teams_open_compose

        result = _tool_teams_open_compose(message="Draft text")
        assert "either a recipient email" in result["error"]

    def test_new_teams_conversation_is_not_created_before_approval(self):
        from skills.teams.tools import _tool_teams_open_compose

        result = _tool_teams_open_compose(
            to="person@example.com",
            to_names="Person Example",
            message="Draft text",
        )
        draft = _drafts.get_draft(result["data"]["draft_id"])
        assert draft is not None
        assert draft["params"]["chat_id"] == ""
        assert "created only after you send" in result["_user_message"].lower()

    def test_teams_and_slack_use_view_labels_not_open_labels(self):
        assert "openLabel: 'View conversation'" in self.APP_JS
        assert "openLabel: data.thread_ts ? 'View conversation' : 'View channel'" in self.APP_JS
        assert "Viewing Teams" in self.APP_JS
        assert "Viewing Slack" in self.APP_JS

    def test_no_teams_view_action_without_existing_chat_id(self):
        assert "viewAvailable: Boolean(data.chat_id)" in self.APP_JS
        assert "A new Teams conversation will be created only after you send." in self.APP_JS

    def test_no_unsupported_compose_injection(self):
        # The product contract deliberately avoids pretending an external app
        # has received the Gator draft. No DOM compose injection is present.
        assert "teams-pane:open-draft" not in self.APP_JS
        assert "insertText" not in self.APP_JS

    def test_people_lookup_is_a_supported_compact_path(self):
        from skills.teams.tools import TOOL_DEFS

        read_tool = next(t for t in TOOL_DEFS if t["name"] == "read_teams_chats")
        assert "person_email" in read_tool["input_schema"]["properties"]
        assert "resolved contact email" in read_tool["description"]


class TestSlackTypedDestinations:
    """Slack names are display-only: drafts must retain workspace and IDs."""

    def test_channel_draft_binds_workspace_and_channel_id(self):
        from skills.slack.tools import _handle_slack_send_message

        with patch("skills.slack.mcp_client._load_token", return_value={"team_id": "T1", "team": "AMD"}), \
             patch("skills.slack.tools._api", return_value={"ok": True, "channel": {"name": "eng"}}):
            result = _handle_slack_send_message(
                channel_id="C1", team_id="T1", message="Deploying now", thread_ts="123.4"
            )
        assert result["_draft"] == "slack-post"
        assert result["data"]["channel_id"] == "C1"
        assert result["data"]["team_id"] == "T1"
        assert result["data"]["thread_ts"] == "123.4"
        draft = _drafts.get_draft(result["data"]["draft_id"])
        assert draft["params"]["workspace_name"] == "AMD"

    def test_dm_draft_retains_user_id_without_opening_conversation(self):
        from skills.slack.tools import _handle_slack_send_message

        with patch("skills.slack.mcp_client._load_token", return_value={"team_id": "T1", "team": "AMD"}), \
             patch("skills.slack.tools._resolve_user", return_value="Jane Smith"):
            result = _handle_slack_send_message(user_id="U1", team_id="T1", message="Hello")
        assert result["_draft"] == "slack-dm"
        draft = _drafts.get_draft(result["data"]["draft_id"])
        assert draft["params"]["user_id"] == "U1"
        assert draft["params"]["channel_id"] == ""

    def test_workspace_mismatch_rejected_before_draft(self):
        from skills.slack.tools import _handle_slack_send_message

        with patch("skills.slack.mcp_client._load_token", return_value={"team_id": "T2", "team": "Other"}):
            result = _handle_slack_send_message(channel_id="C1", team_id="T1", message="Hello")
        assert "different workspace" in result["error"]

    def test_missing_workspace_identity_rejected_before_draft(self):
        from skills.slack.tools import _handle_slack_send_message

        with patch("skills.slack.mcp_client._load_token", return_value={"team_id": "", "team": "AMD"}):
            result = _handle_slack_send_message(channel_id="C1", team_id="T1", message="Hello")
        assert "identity is unavailable" in result["error"]

    def test_approve_dm_opens_conversation_only_after_approval(self):
        client = TestClient(app)
        did = _drafts.create_draft(
            "slack-dm",
            {"user_id": "U1", "channel_id": "", "team_id": "T1", "message": "Hello"},
            {},
        )

        def slack_api(api_method, params, method="GET"):
            if api_method == "conversations.open":
                return {"ok": True, "channel": {"id": "D1"}}
            if api_method == "chat.postMessage":
                assert params["channel"] == "D1"
                return {"ok": True, "ts": "123.4"}
            raise AssertionError(api_method)

        with patch("skills.slack.mcp_client._load_token", return_value={"team_id": "T1"}), \
             patch("routes.slack._slack_web_api", side_effect=slack_api):
            response = _approve(client, did)
        assert response.status_code == 200, response.text
        assert response.json()["navigate_to"] == {"app": "slack", "channel_id": "D1"}

    def test_workspace_changed_after_draft_blocks_post(self):
        client = TestClient(app)
        did = _drafts.create_draft(
            "slack-post",
            {"channel_id": "C1", "team_id": "T1", "message": "Hello"},
            {},
        )
        with patch("skills.slack.mcp_client._load_token", return_value={"team_id": "T2"}), \
             patch("routes.slack._slack_web_api") as post:
            response = _approve(client, did)
        assert response.status_code == 409, response.text
        post.assert_not_called()
        assert _drafts.get_draft(did) is not None

    def test_missing_workspace_on_legacy_draft_blocks_post(self):
        client = TestClient(app)
        did = _drafts.create_draft(
            "slack-post", {"channel_id": "C1", "message": "Hello"}, {}
        )
        with patch("skills.slack.mcp_client._load_token", return_value={"team_id": "T1"}), \
             patch("routes.slack._slack_web_api") as post:
            response = _approve(client, did)
        assert response.status_code == 409, response.text
        post.assert_not_called()

    def test_frontend_preserves_typed_slack_destination_fields(self):
        source = (pathlib.Path(__file__).parent.parent / "web" / "static" / "app.js").read_text(
            encoding="utf-8", errors="replace"
        )
        assert "channel_id: ch.channel_id" in source
        assert "personId: person.user_id" in source
        assert "active_people: activePeopleSnapshot" in source
        assert "type: focused.dataset.channelType" in source
        assert "_lookupProvider !== 'auto'" in source
        assert "Slack · ${slackWorkspaceName}" in source
        assert "_messagingScope = '';" in source

    def test_slack_user_lookup_paginates_beyond_first_page(self):
        source = (pathlib.Path(__file__).parent.parent / "web" / "routes" / "slack.py").read_text(
            encoding="utf-8", errors="replace"
        )
        assert "for _page in range(10)" in source
        assert 'params["cursor"] = cursor' in source
        assert "for _page in range(100)" in source

    def test_slack_user_lookup_can_search_selected_channel_members(self):
        source = (pathlib.Path(__file__).parent.parent / "web" / "routes" / "slack.py").read_text(
            encoding="utf-8", errors="replace"
        )
        assert "channel_id: str = \"\"" in source
        assert '"conversations.members"' in source
        assert '"scope": "channel_members"' in source

    def test_all_provider_picker_does_not_wait_for_slack_before_teams(self):
        source = (pathlib.Path(__file__).parent.parent / "web" / "static" / "app.js").read_text(
            encoding="utf-8", errors="replace"
        )
        assert "Do not put Slack status or its directory query on the Teams critical" in source
        assert "await Promise.allSettled([...requests, statusPromise])" in source
        assert 'src="/static/icons/${icon}"' in source

    def test_channel_picker_has_same_provider_sections_and_parallel_rendering(self):
        source = (pathlib.Path(__file__).parent.parent / "web" / "static" / "app.js").read_text(
            encoding="utf-8", errors="replace"
        )
        assert "Searching Teams channels" in source
        assert "Searching Slack channels" in source
        assert "const byProvider = {" in source
        assert "slackStatusPromise.then" in source

    def test_slack_people_and_channels_warm_off_the_picker_path(self):
        source = (pathlib.Path(__file__).parent.parent / "web" / "routes" / "slack.py").read_text(
            encoding="utf-8", errors="replace"
        )
        assert "def _warm_workspace_directory" in source
        assert "def _warm_workspace_channels" in source
        assert "_warm_workspace_directory(base.get" in source
        assert "_warm_workspace_channels(base.get" in source
        assert "def _warm_channel_members" in source
        assert "ThreadPoolExecutor(max_workers=10)" in source
        assert "_CHANNEL_MEMBER_CACHE_TTL_SECONDS" in source

    def test_concise_thread_read_avoids_duplicate_json_payload(self):
        from skills.slack.tools import _handle_slack_read_thread

        long_text = "x" * 900
        with patch("skills.slack.tools.is_slack_authenticated", return_value=True), \
             patch("skills.slack.mcp_client._load_token", return_value={"team_id": "T1"}), \
             patch("skills.slack.tools._api", return_value={"ok": True, "messages": [
                 {"ts": "1.0", "user": "U1", "text": long_text},
             ]}), \
             patch("skills.slack.tools._resolve_users_in_messages", side_effect=lambda m: m):
            result = _handle_slack_read_thread("C1", "1.0", response_format="concise")
        assert result["response_format"] == "concise"
        assert len(result["messages"][0]["text"]) <= 600
        assert result["messages"][0]["text"].endswith("…")
        assert result["truncated_messages"] == 1
        assert not result["result"].startswith("[")

    def test_thread_read_defaults_to_concise_and_invalid_mode_fails_safe(self):
        from skills.slack.tools import _handle_slack_read_thread

        with patch("skills.slack.tools.is_slack_authenticated", return_value=True), \
             patch("skills.slack.mcp_client._load_token", return_value={"team_id": "T1"}), \
             patch("skills.slack.tools._api", return_value={"ok": True, "messages": []}), \
             patch("skills.slack.tools._resolve_users_in_messages", side_effect=lambda m: m):
            default_result = _handle_slack_read_thread("C1", "1.0")
            invalid_result = _handle_slack_read_thread("C1", "1.0", response_format="unknown")
        assert default_result["response_format"] == "concise"
        assert invalid_result["response_format"] == "concise"

    def test_slack_draft_card_has_scoped_mention_lookup(self):
        source = (pathlib.Path(__file__).parent.parent / "web" / "static" / "app.js").read_text(
            encoding="utf-8", errors="replace"
        )
        assert "function _wireSlackDraftMentionLookup" in source
        assert "/api/slack/users/${encodeURIComponent(trigger.query)}" in source
        assert "toMrkdwn(editArea.value)" in source
        assert "Type <strong>@</strong> to mention a Slack person." in source
        assert "Type two characters to search Slack people" in source
        assert "Loading Slack people" in source
        assert "_fetchSlackPeople(trigger.query" in source

    def test_teams_draft_card_builds_skype_mentions(self):
        source = (pathlib.Path(__file__).parent.parent / "web" / "static" / "app.js").read_text(
            encoding="utf-8", errors="replace"
        )
        assert "function _wireTeamsDraftMentionLookup" in source
        assert 'itemtype="http://schema.skype.com/Mention"' in source
        assert "teamsMentions.toTeamsPayload(editArea.value)" in source
        assert "mentions: teamsMentionPayload.mentions" in source
        assert "function _teamsDraftEditorSeed" in source
        assert "_wireTeamsDraftMentionLookup(editArea, teamsSeed?.selections || [])" in source
        assert "gcc-selected-mentions" in source
        assert "showSelectedMention" in source

    def test_main_composer_selected_people_are_bound_to_delivery_tools(self):
        source = (pathlib.Path(__file__).parent.parent / "web" / "routes" / "chat.py").read_text(
            encoding="utf-8", errors="replace"
        )
        assert "Bind selected main-composer people" in source
        assert 'tool_name == "slack_send_message"' in source
        assert 'tool_name in {"teams_open_compose", "send_teams_message"}' in source

    def test_teams_tool_compiles_selected_main_mention(self):
        from skills.teams.tools import _tool_teams_open_compose

        result = _tool_teams_open_compose(
            to="peer@amd.com",
            message="Hi @Alex McKinney, please review.",
            mentions=[
                {
                    "id": 9,
                    "mentionText": "Alex McKinney",
                    "mentioned": {"user": {"id": "AAD1", "displayName": "Alex McKinney"}},
                }
            ],
        )
        params = _drafts.get_draft(result["data"]["draft_id"])["params"]
        assert 'itemtype="http://schema.skype.com/Mention"' in params["message"]
        assert params["mentions"][0]["mentioned"]["user"]["id"] == "AAD1"

    def test_teams_compiler_repeats_longest_selected_mention(self):
        from skills.teams.tools import _tool_teams_open_compose

        result = _tool_teams_open_compose(
            to="peer@amd.com",
            message="@Alex McKinney and @Alex McKinney",
            mentions=[
                {"mentionText": "Alex", "mentioned": {"user": {"id": "AAD_SHORT"}}},
                {"mentionText": "Alex McKinney", "mentioned": {"user": {"id": "AAD_LONG"}}},
            ],
        )
        params = _drafts.get_draft(result["data"]["draft_id"])["params"]
        assert params["message"].count('itemtype="http://schema.skype.com/Mention"') == 2
        assert all(m["mentioned"]["user"]["id"] == "AAD_LONG" for m in params["mentions"])

    def test_draft_events_are_routed_to_the_request_tab(self):
        source = (pathlib.Path(__file__).parent.parent / "web" / "static" / "app.js").read_text(
            encoding="utf-8", errors="replace"
        )
        assert "const _tabKey = requestTabId" in source
        assert "_routeDraftToTab(requestTabId, msg.draft" in source
        assert "function _storeTabDraft" in source
        assert "_renderTabDrafts(tabId);" in source
        assert "never inject into whichever tab happens to be visible" in source
        assert "if (_activeTabId !== requestTabId) return;" in source
        assert "const _detachStop = ()" in source
        assert "localStorage.removeItem('tab-drafts-' + tabId)" in source

    def test_backup_draft_signal_carries_request_context(self):
        source = (pathlib.Path(__file__).parent.parent / "web" / "routes" / "chat.py").read_text(
            encoding="utf-8", errors="replace"
        )
        assert '"type": "draft_signal"' in source
        assert '"context_id": context_id' in source

    def test_draft_card_prefers_full_body_over_capped_snippets(self):
        source = (pathlib.Path(__file__).parent.parent / "web" / "static" / "app.js").read_text(
            encoding="utf-8", errors="replace"
        )
        assert "const fullBody = data.body || data.message || data.body_snippet || data.message_snippet || '';" in source

    def test_active_slack_channel_prompt_requires_draft_tool(self):
        source = (pathlib.Path(__file__).parent.parent / "web" / "routes" / "chat.py").read_text(
            encoding="utf-8", errors="replace"
        )
        assert "you MUST call slack_send_message" in source
        assert "do not merely print a draft in prose" in source


class TestSlackLegacyPaneApproval:
    """The still-live third-pane routes must obey the same workspace-bound
    HITL invariant as the central draft approval flow."""

    def test_legacy_channel_send_blocks_workspace_switch(self):
        client = TestClient(app)
        with patch("skills.slack.mcp_client._load_token", return_value={"team_id": "T1"}):
            drafted = client.post("/api/slack/channels/C1/post", json={"message": "Hello"})
        assert drafted.status_code == 200, drafted.text
        token = drafted.json()["confirm_token"]
        with patch("skills.slack.mcp_client._load_token", return_value={"team_id": "T2"}), \
             patch("routes.slack._slack_web_api") as post:
            sent = client.post("/api/slack/channels/C1/send", json={"confirm_token": token, "message": "ignored"})
        assert sent.status_code == 409, sent.text
        post.assert_not_called()

    def test_legacy_dm_opens_conversation_only_after_confirm(self):
        client = TestClient(app)
        with patch("skills.slack.mcp_client._load_token", return_value={"team_id": "T1"}):
            drafted = client.post("/api/slack/dm", json={"user_identifier": "U1", "message": "Hello"})
        assert drafted.status_code == 200, drafted.text
        token = drafted.json()["confirm_token"]

        def slack_api(api_method, params, method="GET"):
            if api_method == "conversations.open":
                return {"ok": True, "channel": {"id": "D1"}}
            if api_method == "chat.postMessage":
                assert params["channel"] == "D1"
                return {"ok": True, "ts": "123.4"}
            raise AssertionError(api_method)

        with patch("skills.slack.mcp_client._load_token", return_value={"team_id": "T1"}), \
             patch("routes.slack._slack_web_api", side_effect=slack_api):
            sent = client.post("/api/slack/dm/send", json={"confirm_token": token})
        assert sent.status_code == 200, sent.text
