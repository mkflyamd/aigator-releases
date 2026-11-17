"""Issue #58: calendar invite attendee parsing + HTML body support.

Bug 1: attendees passed as a quoted, semicolon-separated string must be
normalized to bare emails (no quotes, no semicolons).

Bug 2: a body containing HTML (e.g. an <a href> doc link) must reach the
calendar draft unchanged; see tests/test_calendar_draft.py.
"""

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
