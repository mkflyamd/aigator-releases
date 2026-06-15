"""Reply / Reply All / Forward must preserve the original quoted thread — Issue #1.

Graph's createReply/createReplyAll/createForward build a draft whose body already
contains the quoted original thread (and, for forward, the "--- Forwarded
message ---" block). The send path then PATCHed the draft body with ONLY the new
compose text, overwriting and stripping that quoted history. The fix must prepend
the new text to the existing draft body instead of replacing it.
"""
from unittest.mock import patch, MagicMock

from fastapi.testclient import TestClient

from app import app

QUOTED = (
    '<div id="divRplyFwdMsg">From: Alice &lt;alice@x.com&gt;<br>'
    'Sent: Monday<br>Subject: Hi<br><br>original thread body here</div>'
)


def _graph_with_draft_body():
    """Mock Graph: verify GET returns headers; draft GET returns the quoted body;
    createReply/Forward returns a draft id; patch/send are captured."""
    gc = MagicMock()

    def _get(path, params=None):
        sel = ""
        if params:
            sel = str(params.get("$select", ""))
        if "body" in sel:
            return {"id": "DRAFT1", "body": {"contentType": "HTML", "content": QUOTED}}
        return {"id": "M1", "subject": "Hi", "from": {"emailAddress": {"name": "Alice"}}}

    gc.get.side_effect = _get
    gc.post.return_value = {"id": "DRAFT1"}
    return gc


def _last_body_patch(gc):
    patches = [c for c in gc.patch.call_args_list
               if len(c.args) >= 2 and isinstance(c.args[1], dict) and "body" in c.args[1]]
    assert patches, "expected a PATCH that sets the draft body"
    return patches[-1].args[1]["body"]["content"]


class TestReplyPreservesThread:
    def test_reply_keeps_quoted_original(self):
        client = TestClient(app)
        gc = _graph_with_draft_body()
        with patch("skills._m365.helpers.get_graph_client", return_value=gc):
            r = client.post("/api/email/reply",
                            json={"message_id": "M1", "body": "My new reply", "reply_all": False})
        assert r.status_code == 200, r.text
        content = _last_body_patch(gc)
        assert "My new reply" in content
        assert "original thread body here" in content, \
            "reply must preserve the quoted original thread (#1)"
        assert content.index("My new reply") < content.index("original thread body here"), \
            "new reply text must sit above the quoted thread"

    def test_reply_all_keeps_quoted_original(self):
        client = TestClient(app)
        gc = _graph_with_draft_body()
        with patch("skills._m365.helpers.get_graph_client", return_value=gc):
            r = client.post("/api/email/reply",
                            json={"message_id": "M1", "body": "Group reply", "reply_all": True})
        assert r.status_code == 200, r.text
        content = _last_body_patch(gc)
        assert "Group reply" in content
        assert "original thread body here" in content


class TestForwardPreservesThread:
    def test_forward_keeps_forwarded_message(self):
        client = TestClient(app)
        gc = _graph_with_draft_body()
        with patch("skills._m365.helpers.get_graph_client", return_value=gc):
            r = client.post("/api/email/forward",
                            json={"message_id": "M1", "to": "bob@x.com", "comment": "FYI see below"})
        assert r.status_code == 200, r.text
        content = _last_body_patch(gc)
        assert "FYI see below" in content
        assert "original thread body here" in content, \
            "forward must include the original message body (#1)"
        assert content.index("FYI see below") < content.index("original thread body here"), \
            "forward comment must sit above the forwarded message"


class TestAgentDraftApprovePreservesThread:
    """The agent draft-approve path (HITL) must ALSO preserve the quoted thread.

    The UI compose path was fixed, but the agent-drafted reply/forward goes through
    /api/drafts/{id}/approve, which PATCHed the draft body with only the new text —
    re-introducing the #1 strip in the other send path.
    """

    def _approve(self, client, draft_id):
        from security import get_csrf_token
        return client.post(f"/api/drafts/{draft_id}/approve",
                           headers={"X-CSRF-Token": get_csrf_token()})

    def test_approve_reply_keeps_quoted_original(self):
        from skills._drafts import create_draft
        client = TestClient(app)
        gc = _graph_with_draft_body()
        did = create_draft("email-reply",
                           {"message_id": "M1", "body": "Approved reply", "reply_all": False},
                           {"summary": "reply"})
        with patch("skills._m365.helpers.get_graph_client", return_value=gc):
            r = self._approve(client, did)
        assert r.status_code == 200, r.text
        content = _last_body_patch(gc)
        assert "Approved reply" in content
        assert "original thread body here" in content, \
            "agent-approved reply must preserve the quoted thread (#1)"
        assert content.index("Approved reply") < content.index("original thread body here")

    def test_approve_forward_keeps_forwarded_message(self):
        from skills._drafts import create_draft
        client = TestClient(app)
        gc = _graph_with_draft_body()
        did = create_draft("email-forward",
                           {"message_id": "M1", "to": "bob@x.com", "comment": "Approved FYI"},
                           {"summary": "forward"})
        with patch("skills._m365.helpers.get_graph_client", return_value=gc):
            r = self._approve(client, did)
        assert r.status_code == 200, r.text
        content = _last_body_patch(gc)
        assert "Approved FYI" in content
        assert "original thread body here" in content, \
            "agent-approved forward must include the original message body (#1)"
        assert content.index("Approved FYI") < content.index("original thread body here")
