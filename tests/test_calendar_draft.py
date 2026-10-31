import pytest

import skills.calendar.tools as cal
from skills._drafts import get_draft


class _Client:
    def __init__(self):
        self.paths = []

    def post(self, path, body, **kw):
        self.paths.append(path)
        if path.endswith("getSchedule"):
            return {"value": [{"scheduleId": "a@x.com", "workingHours": {
                "startTime": "08:00:00.0000000", "endTime": "17:00:00.0000000",
                "timeZone": {"name": "India Standard Time"}}}]}
        raise AssertionError(f"draft must not call {path}")


@pytest.fixture
def client(monkeypatch):
    import skills._m365.helpers as m365
    import skills.calendar.helpers as cal_helpers

    c = _Client()
    monkeypatch.setattr(m365, "get_cal_client", lambda: c, raising=False)
    monkeypatch.setattr(cal_helpers, "get_user_win_tz", lambda: "Pacific Standard Time", raising=False)
    return c


def _draft(**kw):
    args = dict(subject="Sync", start="2026-11-02T09:00:00", end="2026-11-02T09:30:00",
                attendees=['"A@x.com"; b@y.com'], body="Agenda", teams=True)
    args.update(kw)
    return cal._tool_draft_calendar_event(**args)


def test_draft_never_creates_an_event(client):
    _draft()
    assert "/me/events" not in client.paths


def test_draft_is_stored_and_returned(client):
    out = _draft()
    assert out["_draft"] == "calendar-event"
    stored = get_draft(out["data"]["draft_id"])
    assert stored["type"] == "calendar-event"
    p = stored["params"]
    assert p["subject"] == "Sync" and p["attendees"] == ["A@x.com", "b@y.com"]
    assert p["timezone"] == "Pacific Standard Time" and p["teams"] is True
    assert out["data"]["attendee_local"]["a@x.com"] == "10:30 PM – 11:00 PM IST"


def test_html_body_is_kept(client):
    html = 'Doc: <a href="https://x/Doc.docx">Doc.docx</a>'
    out = _draft(body=html)
    assert get_draft(out["data"]["draft_id"])["params"]["body"] == html


def test_agent_has_no_tool_that_sends_invites():
    assert "create_calendar_event" not in cal.TOOL_HANDLERS
    assert "draft_calendar_event" in cal.TOOL_HANDLERS
    assert "create_calendar_event" not in {t["name"] for t in cal.TOOL_DEFS}
    assert "draft_calendar_event" in {t["name"] for t in cal.TOOL_DEFS}
