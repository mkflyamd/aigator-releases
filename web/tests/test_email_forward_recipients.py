"""Reply/Forward recipient UX — Issues #1 + #21 (full-view rework).

The original inline reply pane was cramped at the bottom of the reading pane, had
no people lookup, and couldn't add/remove recipients — Forward was unusable and
Reply hid recipients. Smoke test failed it.

Rework (user-approved): reply/forward open a FULL-VIEW compose pane
(`_showReplyForwardCompose(mode, email)`) that reuses the chip people-picker
`_buildRecipientField` (autocomplete lookup + add/remove chips) for To/Cc/Bcc. The
createReply/createReplyAll/createForward backend is kept so conversation threading +
the quoted original thread are preserved (the #1 fix). Reply now also accepts optional
to/cc/bcc overrides so editing reply recipients is honest (createReply auto-sets them
otherwise).

The original email is quoted inline inside the Quill editor itself (#129), matching
New Email UX (editor fills the pane, toolbar pinned at bottom) and how mainstream
clients like Gmail/Outlook quote a thread — editable, not a separate read-only block.
"""
import pathlib
from unittest.mock import patch, MagicMock

from fastapi.testclient import TestClient

from app import app

TP_JS = (pathlib.Path(__file__).parent.parent / "static" / "third-pane.js").read_text(encoding="utf-8")


def _rf_region() -> str:
    start = TP_JS.find("function _showReplyForwardCompose")
    assert start != -1, "full-view _showReplyForwardCompose(mode, email) must exist (#1/#21)"
    return TP_JS[start:start + 9000]


class TestFullViewPane:
    def test_function_takes_a_mode(self):
        region = _rf_region()
        assert "_showReplyForwardCompose(mode" in region or "function _showReplyForwardCompose(mode" in region, \
            "reply/forward must funnel through a single mode-driven full-view function (#21)"

    def test_reuses_chip_people_picker(self):
        region = _rf_region()
        assert "_buildRecipientField(" in region, \
            "full-view pane must reuse the chip people-picker with lookup/add/remove (#21)"

    def test_shows_original_email_quoted_inline(self):
        region = _rf_region()
        assert "_injectQuoted" in region and "dangerouslyPasteHTML" in region, \
            "the original email must be quoted inline inside the Quill editor (#129)"

    def test_sets_mode_correct_header(self):
        region = _rf_region()
        assert "'Forward'" in region, "forward mode must title the pane 'Forward' (#21)"
        assert "Reply" in region, "reply modes must title the pane with Reply (#21)"


class TestButtonsWireToFullView:
    def test_three_actions_open_full_view(self):
        # The reading-pane action bar buttons must open the new full-view function.
        assert "_showReplyForwardCompose('forward'" in TP_JS, "Forward button must open full-view (#21)"
        assert "_showReplyForwardCompose('reply'" in TP_JS, "Reply button must open full-view (#21)"
        assert "_showReplyForwardCompose('replyall'" in TP_JS, "Reply All button must open full-view (#21)"

    def test_send_targets_threaded_backends(self):
        region = _rf_region()
        assert "/api/email/reply" in region, "reply/replyall must POST to the threaded reply backend (#1)"
        assert "/api/email/forward" in region, "forward must POST to the forward backend (#1)"


class TestForwardBackendHonorsCcBcc:
    def _mock_graph(self):
        gc = MagicMock()

        def _get(path, params=None):
            if "$select" in (params or {}) and "body" in params["$select"]:
                return {"body": {"contentType": "HTML", "content": "<p>original</p>"}}
            return {"id": "MSG1", "subject": "Hi"}

        def _post(path, body=None):
            if path.endswith("/createForward"):
                return {"id": "DRAFT1"}
            return {}

        gc.get.side_effect = _get
        gc.post.side_effect = _post
        gc.patch.return_value = {}
        return gc

    def test_forward_sets_cc_and_bcc_recipients(self):
        client = TestClient(app)
        gc = self._mock_graph()
        with patch("skills._m365.helpers.get_graph_client", return_value=gc):
            r = client.post("/api/email/forward", json={
                "message_id": "MSG1",
                "to": "a@x.com",
                "cc": "b@x.com",
                "bcc": "c@x.com",
                "comment": "fyi",
            })
        assert r.status_code == 200, r.text
        patch_update = gc.patch.call_args.args[1]
        cc_addrs = [r["emailAddress"]["address"] for r in patch_update.get("ccRecipients", [])]
        bcc_addrs = [r["emailAddress"]["address"] for r in patch_update.get("bccRecipients", [])]
        assert cc_addrs == ["b@x.com"], "forward must honor the Cc field (#21)"
        assert bcc_addrs == ["c@x.com"], "forward must honor the Bcc field (#21)"


class TestReplyBackendHonorsRecipientOverrides:
    """Reply must apply edited recipients when provided, else keep createReply defaults (#21)."""

    def _mock_graph(self):
        gc = MagicMock()

        def _get(path, params=None):
            if "$select" in (params or {}) and "body" in params["$select"]:
                return {"body": {"contentType": "HTML", "content": "<p>quoted</p>"}}
            return {"id": "MSG1", "subject": "Hi", "from": {"emailAddress": {"name": "Jane"}}}

        def _post(path, body=None):
            if path.endswith("/createReply") or path.endswith("/createReplyAll"):
                return {"id": "DRAFT1"}
            return {}

        gc.get.side_effect = _get
        gc.post.side_effect = _post
        gc.patch.return_value = {}
        return gc

    def test_reply_applies_to_override_when_provided(self):
        client = TestClient(app)
        gc = self._mock_graph()
        with patch("skills._m365.helpers.get_graph_client", return_value=gc):
            r = client.post("/api/email/reply", json={
                "message_id": "MSG1",
                "body": "thanks",
                "reply_all": False,
                "to": "new@x.com",
                "cc": "cc@x.com",
            })
        assert r.status_code == 200, r.text
        # Collect every recipient set across all patch calls on the draft.
        to_addrs, cc_addrs = [], []
        for call in gc.patch.call_args_list:
            upd = call.args[1]
            to_addrs += [x["emailAddress"]["address"] for x in upd.get("toRecipients", [])]
            cc_addrs += [x["emailAddress"]["address"] for x in upd.get("ccRecipients", [])]
        assert "new@x.com" in to_addrs, "reply must apply the edited To recipients (#21)"
        assert "cc@x.com" in cc_addrs, "reply must apply the edited Cc recipients (#21)"

    def test_reply_without_overrides_keeps_createreply_defaults(self):
        client = TestClient(app)
        gc = self._mock_graph()
        with patch("skills._m365.helpers.get_graph_client", return_value=gc):
            r = client.post("/api/email/reply", json={
                "message_id": "MSG1",
                "body": "thanks",
                "reply_all": False,
            })
        assert r.status_code == 200, r.text
        # No recipient keys should be patched when the user didn't edit them —
        # createReply already set the correct recipients server-side.
        for call in gc.patch.call_args_list:
            upd = call.args[1]
            assert "toRecipients" not in upd, "must not override recipients when none provided (#21)"
            assert "ccRecipients" not in upd
