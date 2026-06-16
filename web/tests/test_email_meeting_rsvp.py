"""Accept/decline from the Outlook email pane must persist — Issue #2.

RSVP from the in-app calendar pop-up works (it posts a REAL calendar event id to
/api/calendar/events/{id}/respond). RSVP from the email pane did NOT persist: it
posted `email.event_id` — a value the backend resolves by a fuzzy subject
`contains(...)` search over the calendar (top-1, newest-first) — which is often
empty or points at the wrong/duplicate event, so Graph accept/decline silently
no-ops on the user's real invitation.

The robust fix is message-based RSVP: respond against the invitation message
itself via Graph `POST /me/messages/{message_id}/{response}` (what Outlook does),
keyed off the message id we always have — no fragile subject search.
"""
import pathlib
from unittest.mock import patch, MagicMock

from fastapi.testclient import TestClient

from app import app

TP_JS = (pathlib.Path(__file__).parent.parent / "static" / "third-pane.js").read_text(encoding="utf-8")


class TestEmailRsvpUsesMessageEndpoint:
    """The email pane must RSVP via the message-keyed endpoint, not the calendar
    endpoint with the fuzzy event_id."""

    def _rsvp_region(self) -> str:
        idx = TP_JS.find("tp-rsvp-accept")
        assert idx != -1, "RSVP bar not found in third-pane.js"
        # The sendRsvp fetch sits just below the bar markup.
        return TP_JS[idx:idx + 1500]

    def test_rsvp_posts_to_message_respond_endpoint(self):
        region = self._rsvp_region()
        assert "/api/email/messages/" in region and "/respond" in region, (
            "email-pane RSVP must post to /api/email/messages/{id}/respond (#2)"
        )

    def test_rsvp_no_longer_uses_fuzzy_event_id(self):
        region = self._rsvp_region()
        assert "/api/calendar/events/" not in region, (
            "email-pane RSVP must not route through the calendar endpoint (#2)"
        )
        assert "email.event_id" not in region, (
            "email-pane RSVP must key off the message id, not the fuzzy event_id (#2)"
        )


class TestRespondBackendIsMessageBased:
    def _mock_graph(self):
        gc = MagicMock()
        gc.post.return_value = {}
        return gc

    def test_respond_calls_graph_message_accept(self):
        client = TestClient(app)
        gc = self._mock_graph()
        with patch("skills._m365.helpers.get_graph_client", return_value=gc):
            r = client.post("/api/email/messages/MSG1/respond",
                            json={"response": "accept", "send_response": True})
        assert r.status_code == 200, r.text
        path = gc.post.call_args.args[0]
        assert path == "/me/messages/MSG1/accept", (
            "respond must target the invitation message, not a subject-matched event (#2)"
        )

    def test_respond_validates_response_value(self):
        client = TestClient(app)
        gc = self._mock_graph()
        with patch("skills._m365.helpers.get_graph_client", return_value=gc):
            r = client.post("/api/email/messages/MSG1/respond",
                            json={"response": "bogus", "send_response": True})
        assert r.status_code == 400, r.text
        assert gc.post.call_count == 0
