"""Outlook native-pane HITL regression tests.

Native Outlook mode hides the classic third-pane compose form, so an
agent-drafted email is approved via an in-chat draft-approval card that POSTs
to /api/drafts/{id}/approve. These tests lock the human-in-the-loop invariants
for that path (per CLAUDE.md: email must NEVER auto-send):

  1. The agent's compose tool only CREATES a draft + emits a pane signal — it
     never sends.
  2. Approving an 'email-send' draft sends via Graph /me/sendMail with the
     drafted recipients/subject/body.
  3. The approval-card textarea edit (edited_message) overrides the draft body.
  4. Approve is CSRF-gated — the in-process agent loop cannot forge the header,
     so there is no agent-reachable auto-send path.
  5. An 'email-send' draft with no recipients is rejected before any send.

Also asserts the pin-orb "Open" deep-link builds the OWA conversation route
(/mail/inbox/id/<convid>) that the spike proved resolves a pinned message.
"""
import pathlib
from unittest.mock import patch, MagicMock

from fastapi.testclient import TestClient

from app import app


def _graph_capture():
    """Mock Graph client that records sendMail payloads."""
    gc = MagicMock()
    gc.get.return_value = {"id": "M1"}
    gc.post.return_value = {"id": "DRAFT1"}
    return gc


def _sendmail_payload(gc):
    calls = [c for c in gc.post.call_args_list
             if c.args and c.args[0] == "/me/sendMail"]
    assert calls, "expected a POST to /me/sendMail"
    return calls[-1].args[1]["message"]


def _approve(client, draft_id, body=None):
    from security import get_csrf_token
    return client.post(f"/api/drafts/{draft_id}/approve",
                       headers={"X-CSRF-Token": get_csrf_token()},
                       json=body)


class TestComposeToolIsDraftOnly:
    """The agent tool must create a draft + pane signal and NOT send."""

    def test_open_compose_creates_email_send_draft_and_pane_signal(self):
        from skills.email.tools import _tool_email_open_compose
        from skills._drafts import _pending_drafts

        gc = _graph_capture()
        with patch("skills._m365.helpers.get_graph_client", return_value=gc):
            res = _tool_email_open_compose(
                to="bob@amd.com", subject="Status", body="Here is the status.")

        assert res["_pane"] == "email-compose"
        draft_id = res["data"]["draft_id"]
        assert draft_id in _pending_drafts
        assert _pending_drafts[draft_id]["type"] == "email-send"
        # Draft-only: the tool must never call sendMail itself.
        assert not any(c.args and c.args[0] == "/me/sendMail"
                       for c in gc.post.call_args_list), \
            "compose tool must NOT auto-send — draft only (CLAUDE.md HITL)"


class TestApproveEmailSend:
    def test_approve_sends_with_drafted_fields(self):
        from skills._drafts import create_draft
        client = TestClient(app)
        gc = _graph_capture()
        did = create_draft("email-send",
                           {"to": "bob@amd.com", "subject": "Q3 plan",
                            "body": "Draft body text."},
                           {"to": ["bob@amd.com"], "subject": "Q3 plan"})
        with patch("skills._m365.helpers.get_graph_client", return_value=gc):
            r = _approve(client, did)
        assert r.status_code == 200, r.text
        msg = _sendmail_payload(gc)
        assert msg["subject"] == "Q3 plan"
        assert msg["toRecipients"] == [{"emailAddress": {"address": "bob@amd.com"}}]
        assert "Draft body text." in msg["body"]["content"]

    def test_edited_message_overrides_body(self):
        from skills._drafts import create_draft
        client = TestClient(app)
        gc = _graph_capture()
        did = create_draft("email-send",
                           {"to": "bob@amd.com", "subject": "Q3 plan",
                            "body": "ORIGINAL DRAFT"},
                           {"to": ["bob@amd.com"], "subject": "Q3 plan"})
        with patch("skills._m365.helpers.get_graph_client", return_value=gc):
            r = _approve(client, did, body={"edited_message": "HUMAN EDITED TEXT"})
        assert r.status_code == 200, r.text
        content = _sendmail_payload(gc)["body"]["content"]
        assert "HUMAN EDITED TEXT" in content
        assert "ORIGINAL DRAFT" not in content, \
            "the approval-card edit must override the drafted body"

    def test_no_recipients_rejected_before_send(self):
        from skills._drafts import create_draft
        client = TestClient(app)
        gc = _graph_capture()
        did = create_draft("email-send",
                           {"to": "", "subject": "Oops", "body": "no recipient"},
                           {"to": [], "subject": "Oops"})
        with patch("skills._m365.helpers.get_graph_client", return_value=gc):
            r = _approve(client, did)
        assert r.status_code == 400, r.text
        assert not any(c.args and c.args[0] == "/me/sendMail"
                       for c in gc.post.call_args_list), \
            "must not send when there are no recipients"


class TestApproveIsCsrfGated:
    """Without a valid CSRF token the send is blocked. The agent loop has no way
    to read window.__CSRF_TOKEN__, so this is what keeps agent email draft-only.
    """

    def test_approve_without_csrf_is_rejected(self):
        from skills._drafts import create_draft, _pending_drafts
        client = TestClient(app)
        gc = _graph_capture()
        did = create_draft("email-send",
                           {"to": "bob@amd.com", "subject": "x", "body": "y"},
                           {"to": ["bob@amd.com"], "subject": "x"})
        with patch("skills._m365.helpers.get_graph_client", return_value=gc):
            r = client.post(f"/api/drafts/{did}/approve")  # no X-CSRF-Token
        assert r.status_code in (401, 403), r.text
        assert not any(c.args and c.args[0] == "/me/sendMail"
                       for c in gc.post.call_args_list), \
            "no send may occur without CSRF approval"
        # Draft must survive a rejected (non-consuming) approval so the human can retry.
        assert did in _pending_drafts


class TestOpenDeepLinkRoute:
    """Pin-orb 'Open' for an Outlook pin deep-links via the OWA conversation
    route the spike verified: /mail/inbox/id/<convid>."""

    MAIN = (pathlib.Path(__file__).parent.parent.parent
            / "shell" / "main.js").read_text(encoding="utf-8")

    def test_navigate_pin_builds_owa_conversation_route(self):
        start = self.MAIN.find("outlook-pane:navigate-pin")
        assert start != -1, "outlook-pane:navigate-pin handler not found"
        body = self.MAIN[start:start + 500]
        assert "/mail/inbox/id/" in body
        assert "encodeURIComponent" in body, \
            "convid must be URL-encoded (it can contain '=' and '+')"


class TestOpenPinnedEmailResolvesConversationId:
    """Opening a pinned Outlook email must work even though the pinned id is a
    conversationId (OWA's data-convid), not a message id.

    Graph's GET /me/messages/{id} 400s on a conversationId:
      'ConversationId isn't supported in the context of this operation.'
    _tool_get_email_detail must catch that and resolve the newest message in the
    conversation via $filter=conversationId eq '<id>', instead of erroring out
    and forcing a subject-search fallback.
    """

    # Ids deliberately contain the base64url chars that broke the path before
    # (_enc_id fix): '/', '+', '='. The tool must percent-encode them so Graph
    # doesn't split the id into path segments ("Resource not found for the
    # segment ...").
    CONV_ID = "AAQkAD/conv+Id=kXzQ=="
    MSG_ID = "AAMkAD/real+Msg=kXzQ=="

    def _gc(self):
        import urllib.parse
        gc = MagicMock()
        detail = {
            "id": self.MSG_ID,
            "subject": "New Time Proposed: Skills/CLI-TUI regroup post AAI",
            "from": {"emailAddress": {"name": "Mrinal Karvir", "address": "mrinal@amd.com"}},
            "toRecipients": [], "ccRecipients": [], "bccRecipients": [],
            "receivedDateTime": "2026-07-29T14:30:00Z",
            "body": {"contentType": "text", "content": "Will 30 mins before work?"},
            "isRead": True, "importance": "normal", "conversationId": self.CONV_ID,
        }

        def _get(path, params=None):
            # New approach: _fetch_message_by_id uses $filter=id eq '...' to avoid
            # path-segment issues with '/' in message ids.
            if path == "/me/messages":
                f = params.get("$filter", "") if params else ""
                # Case 1: direct message id lookup via $filter=id eq
                if f"id eq '{self.MSG_ID}'" in f:
                    return {"value": [detail]}
                # Case 2: id lookup for conv id returns nothing (not a message id)
                if f"id eq '{self.CONV_ID}'" in f:
                    return {"value": []}
                # Case 3: conversationId fallback lookup
                if "conversationId eq" in f:
                    assert "$orderby" not in params, \
                        "conversationId $filter must not be combined with $orderby (Graph 400)"
                    return {"value": [
                        {"id": "OLDER", "receivedDateTime": "2026-07-28T09:00:00Z"},
                        {"id": self.MSG_ID, "receivedDateTime": "2026-07-29T14:30:00Z"},
                    ]}
                raise AssertionError(f"unexpected $filter: {f}")
            # Direct path fallback (should not be used for new pins, only old-format)
            if path.startswith("/me/messages/"):
                seg = path[len("/me/messages/"):]
                decoded = urllib.parse.unquote(seg)
                if decoded == self.MSG_ID:
                    return detail
                raise AssertionError(f"unexpected message id segment: {seg}")
            raise AssertionError(f"unexpected Graph GET: {path}")

        gc.get.side_effect = _get
        return gc

    def test_pinned_conversation_id_resolves_and_opens(self):
        from skills.email.tools import _tool_get_email_detail
        gc = self._gc()
        with patch("skills._m365.helpers.get_graph_client", return_value=gc):
            result = _tool_get_email_detail(self.CONV_ID)
        assert "error" not in result, result
        assert result["id"] == self.MSG_ID
        assert result["subject"].startswith("New Time Proposed")
        assert "30 mins" in result["body"]

    def test_real_message_id_still_works_without_fallback(self):
        from skills.email.tools import _tool_get_email_detail
        gc = self._gc()
        with patch("skills._m365.helpers.get_graph_client", return_value=gc):
            result = _tool_get_email_detail(self.MSG_ID)
        assert "error" not in result, result
        assert result["id"] == self.MSG_ID
        # Real message id: resolved via $filter=id eq — no conversationId fallback.
        calls = gc.get.call_args_list
        conv_fallback_calls = [
            c for c in calls
            if c.args and c.args[0] == "/me/messages"
            and c.kwargs.get("params", {}).get("$filter", "").startswith("conversationId eq")
        ]
        assert not conv_fallback_calls, \
            "a real message id must not trigger the conversationId fallback"
