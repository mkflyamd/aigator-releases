"""Accept/decline from the Outlook email pane must persist — Issue #2, superseded by #137.

RSVP from the in-app calendar pop-up works (it posts a REAL calendar event id to
/api/calendar/events/{id}/respond). RSVP from the email pane did NOT persist: the
original #2 fix tried Graph `POST /me/messages/{id}/{response}` — Outlook's own
message-based RSVP — but Graph rejects it outright ("Resource not found for segment
'accept'"), because that action isn't exposed on plain mail messages (#137).

The #137 fix keeps the message-keyed frontend endpoint (`/api/email/messages/{id}/respond`,
so the UI still just needs the message id) but resolves the REAL calendar event id
server-side — via the `/event` navigation property, then iCalUId, then a subject+date
match — and RSVPs against `/me/events/{event_id}/{response}`, the only endpoint Graph
actually accepts.
"""
import pathlib
from unittest.mock import patch, MagicMock

from fastapi.testclient import TestClient

from app import app

TP_JS = (pathlib.Path(__file__).parent.parent / "static" / "third-pane.js").read_text(encoding="utf-8")


class TestEmailRsvpUsesMessageEndpoint:
    """The email pane must RSVP via the message-keyed endpoint; event-id resolution
    is the backend's job (#137)."""

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

    def test_rsvp_does_not_route_through_calendar_endpoint(self):
        region = self._rsvp_region()
        assert "/api/calendar/events/" not in region, (
            "email-pane RSVP must not route through the calendar endpoint directly — "
            "the backend resolves the real event id server-side (#137)"
        )


class TestRespondBackendIsMessageBased:
    def _mock_clients(self, event_id="EVT1"):
        gc = MagicMock()
        gc.get.return_value = {"id": event_id}
        gc.post.return_value = {}
        cal_gc = MagicMock()
        return gc, cal_gc

    def test_respond_resolves_event_via_nav_property_and_posts_to_calendar(self):
        client = TestClient(app)
        gc, cal_gc = self._mock_clients()
        with patch("skills._m365.helpers.get_graph_client", return_value=gc), \
             patch("skills._m365.helpers.get_cal_client", return_value=cal_gc):
            r = client.post("/api/email/messages/MSG1/respond",
                            json={"response": "accept", "send_response": True})
        assert r.status_code == 200, r.text
        path = gc.post.call_args.args[0]
        assert path == "/me/events/EVT1/accept", (
            "respond must resolve the real calendar event id and target "
            "/me/events/{id}/accept — /me/messages/{id}/accept returns "
            "400 'segment accept' (#137)"
        )

    def test_respond_uses_frontend_supplied_event_id_when_present(self):
        client = TestClient(app)
        gc, cal_gc = self._mock_clients()
        with patch("skills._m365.helpers.get_graph_client", return_value=gc), \
             patch("skills._m365.helpers.get_cal_client", return_value=cal_gc):
            r = client.post("/api/email/messages/MSG1/respond",
                            json={"response": "decline", "send_response": True,
                                  "event_id": "EVT-FROM-EMAIL"})
        assert r.status_code == 200, r.text
        path = gc.post.call_args.args[0]
        assert path == "/me/events/EVT-FROM-EMAIL/decline"
        assert not any(
            c.args and c.args[0] == "/me/messages/MSG1/event" for c in gc.get.call_args_list
        ), "a frontend-supplied event_id must skip the nav-property lookup entirely"

    def test_respond_422_when_event_cannot_be_resolved(self):
        client = TestClient(app)
        gc = MagicMock()
        gc.get.side_effect = Exception("not found")
        cal_gc = MagicMock()
        cal_gc.get.return_value = {"value": []}
        with patch("skills._m365.helpers.get_graph_client", return_value=gc), \
             patch("skills._m365.helpers.get_cal_client", return_value=cal_gc):
            r = client.post("/api/email/messages/MSG1/respond",
                            json={"response": "accept", "send_response": True})
        assert r.status_code == 422, r.text

    def test_respond_validates_response_value(self):
        client = TestClient(app)
        gc, cal_gc = self._mock_clients()
        with patch("skills._m365.helpers.get_graph_client", return_value=gc), \
             patch("skills._m365.helpers.get_cal_client", return_value=cal_gc):
            r = client.post("/api/email/messages/MSG1/respond",
                            json={"response": "bogus", "send_response": True})
        assert r.status_code == 400, r.text
        assert gc.post.call_count == 0
