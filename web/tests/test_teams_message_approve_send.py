"""Approving a drafted Teams message must actually send it.

Regression: the approve handler POSTed to a HARDCODED http://localhost:8000/
api/teams/send-message. The dev server runs on 8003, so the self-call hit a dead
port — the draft was created but sending silently failed. The fix calls
tp_teams_send_message() directly in-process (no port dependency), matching the
Slack/email branches.
"""

import pathlib
from unittest.mock import AsyncMock, patch

from fastapi.testclient import TestClient

from app import app

EMAIL_SRC = (pathlib.Path(__file__).parent.parent / "routes" / "email.py").read_text(
    encoding="utf-8"
)


def _approve(client, draft_id, body=None):
    from security import get_csrf_token

    return client.post(
        f"/api/drafts/{draft_id}/approve",
        headers={"X-CSRF-Token": get_csrf_token()},
        json=body,
    )


class TestTeamsApproveSend:
    def test_approve_calls_send_handler_directly(self):
        from skills._drafts import create_draft

        client = TestClient(app)
        did = create_draft(
            "teams-message",
            {
                "to": "",
                "message": "Fireworks update text",
                "chat_id": "19:71880fe368394488b0ba77ef34ac1967@thread.v2",
                "recipients": [],
                "mentions": [],
            },
            {"message_snippet": "Fireworks update text"},
        )
        fake_send = AsyncMock(
            return_value={
                "sent": True,
                "chat_id": "19:71880...",
                "message_id": "1785900000000",
            }
        )
        with patch("routes.teams.tp_teams_send_message", fake_send):
            r = _approve(client, did)
        assert r.status_code == 200, r.text
        assert r.json().get("sent") is True
        # The send handler was invoked in-process with the drafted fields.
        fake_send.assert_awaited_once()
        sent_req = fake_send.await_args.args[0]
        assert sent_req.message == "Fireworks update text"
        assert sent_req.chat_id == "19:71880fe368394488b0ba77ef34ac1967@thread.v2"

    def test_edited_message_is_sent(self):
        from skills._drafts import create_draft

        client = TestClient(app)
        did = create_draft(
            "teams-message",
            {
                "to": "",
                "message": "ORIGINAL",
                "chat_id": "19:abc@thread.v2",
                "recipients": [],
                "mentions": [],
            },
            {"message_snippet": "ORIGINAL"},
        )
        fake_send = AsyncMock(return_value={"sent": True})
        with patch("routes.teams.tp_teams_send_message", fake_send):
            r = _approve(client, did, body={"edited_message": "HUMAN EDITED"})
        assert r.status_code == 200, r.text
        sent_req = fake_send.await_args.args[0]
        assert sent_req.message == "HUMAN EDITED"


class TestNoHardcodedPort:
    def test_approve_handler_has_no_hardcoded_localhost_port(self):
        """Lock the fix: the teams-message branch must not self-POST to a fixed port."""
        assert '"http://localhost:8000/api/teams/send-message"' not in EMAIL_SRC, (
            "teams-message approval must not POST to a hardcoded localhost:8000 — "
            "call tp_teams_send_message() directly instead"
        )
        # And it must import/call the handler directly.
        assert "tp_teams_send_message" in EMAIL_SRC, (
            "teams-message approval must call tp_teams_send_message directly"
        )
