"""Issue #58: calendar invite attendee parsing + HTML body support.

Bug 1: attendees passed as a quoted, semicolon-separated string must be
normalized to bare emails (no quotes, no semicolons).

Bug 2: a body containing HTML (e.g. an <a href> doc link) must be sent to Graph
with contentType "HTML" so the link is clickable, while a plain-text body stays
contentType "text".
"""
import re

from skills.calendar.tools import _parse_email_list


def test_parse_email_list_strips_quotes_and_semicolons():
    raw = '"Mrinal.Karvir@amd.com"; "Satya.Devineni@amd.com"; "Haichen.Zhang@amd.com"'
    out = _parse_email_list(raw)
    assert out == [
        "Mrinal.Karvir@amd.com",
        "Satya.Devineni@amd.com",
        "Haichen.Zhang@amd.com",
    ]
    for addr in out:
        assert '"' not in addr and ";" not in addr


def test_parse_email_list_dedupes_case_insensitively():
    out = _parse_email_list(["a@b.com", "A@B.com", "c@d.com"])
    assert out == ["a@b.com", "c@d.com"]


def test_create_event_sends_html_body_when_tags_present(monkeypatch):
    import skills.calendar.tools as cal

    captured = {}

    class _FakeClient:
        def post(self, path, body):
            captured["body"] = body
            return {"id": "evt1", "subject": body.get("subject", "")}

    monkeypatch.setattr(cal, "get_cal_client", lambda: _FakeClient(), raising=False)
    # get_cal_client is imported inside the function from .._m365.helpers, so patch there too.
    import skills._m365.helpers as helpers
    monkeypatch.setattr(helpers, "get_cal_client", lambda: _FakeClient(), raising=False)
    import skills.calendar.helpers as cal_helpers
    monkeypatch.setattr(cal_helpers, "get_user_win_tz", lambda: "UTC", raising=False)
    monkeypatch.setattr(cal_helpers, "fmt_cal_time", lambda s: s, raising=False)

    html_body = 'Sync. Doc: <a href="https://x/Doc.docx">Doc.docx</a>'
    cal._tool_create_calendar_event(
        subject="Sync", start="2026-06-15T10:00:00", end="2026-06-15T10:30:00",
        body=html_body,
    )
    assert captured["body"]["body"]["contentType"] == "HTML"

    plain_body = "Just a plain agenda line, no markup."
    cal._tool_create_calendar_event(
        subject="Sync", start="2026-06-15T10:00:00", end="2026-06-15T10:30:00",
        body=plain_body,
    )
    assert captured["body"]["body"]["contentType"] == "text"
