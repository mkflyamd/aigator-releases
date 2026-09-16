"""Safety tests for adding attendees to an existing Outlook event.

The legacy tool name is forward_calendar_event, but its supported operation is
an attendee mutation. These tests prevent string recipients becoming character
attendees and prevent recurring-series or mismatched-occurrence mutations.
"""
from unittest.mock import MagicMock, patch

from skills.calendar.tools import _tool_forward_calendar_event
from skills._m365 import helpers as m365_helpers


def _event(**overrides):
    base = {
        "subject": "Cohere Internal Sync",
        "isOrganizer": True,
        "type": "occurrence",
        "start": {"dateTime": "2026-09-14T11:30:00"},
        "attendees": [],
    }
    base.update(overrides)
    return base


def test_string_recipient_is_one_complete_attendee_not_characters():
    gc = MagicMock()
    gc.get.side_effect = [
        _event(),
        {"attendees": [{"emailAddress": {"address": "Marc.Charest@amd.com"}}]},
    ]
    with patch.object(m365_helpers, "get_cal_client", return_value=gc):
        result = _tool_forward_calendar_event(
            "EVENT1",
            "Marc.Charest@amd.com",
            expected_subject="Cohere Internal Sync",
            expected_start="2026-09-14",
        )

    assert result["updated"] is True
    payload = gc.patch.call_args.args[1]
    assert payload["attendees"] == [
        {
            "emailAddress": {"address": "Marc.Charest@amd.com"},
            "type": "required",
            "status": {"response": "none"},
        }
    ]


def test_comma_and_quoted_recipients_are_normalized_and_deduplicated():
    gc = MagicMock()
    gc.get.side_effect = [
        _event(),
        {"attendees": [
            {"emailAddress": {"address": "Marc.Charest@amd.com"}},
            {"emailAddress": {"address": "Second.Person@amd.com"}},
        ]},
    ]
    with patch.object(m365_helpers, "get_cal_client", return_value=gc):
        result = _tool_forward_calendar_event(
            "EVENT1",
            '"Marc.Charest@amd.com"; second.person@amd.com, MARC.CHAREST@amd.com',
            expected_start="2026-09-14",
        )

    assert result["updated"] is True
    addresses = [a["emailAddress"]["address"] for a in gc.patch.call_args.args[1]["attendees"]]
    assert addresses == ["Marc.Charest@amd.com", "second.person@amd.com"]


def test_series_master_is_rejected_without_patch():
    gc = MagicMock()
    gc.get.return_value = _event(type="seriesMaster")
    with patch.object(m365_helpers, "get_cal_client", return_value=gc):
        result = _tool_forward_calendar_event(
            "SERIES1", ["Marc.Charest@amd.com"], expected_start="2026-09-14"
        )

    assert result["updated"] is False
    assert "series master" in result["error"]
    gc.patch.assert_not_called()


def test_expected_date_mismatch_is_rejected_without_patch():
    gc = MagicMock()
    gc.get.return_value = _event()
    with patch.object(m365_helpers, "get_cal_client", return_value=gc):
        result = _tool_forward_calendar_event(
            "EVENT1", ["Marc.Charest@amd.com"], expected_start="2026-09-15"
        )

    assert result["updated"] is False
    assert "date mismatch" in result["error"]
    gc.patch.assert_not_called()


def test_expected_time_mismatch_is_rejected_without_patch():
    gc = MagicMock()
    gc.get.return_value = _event()
    with patch.object(m365_helpers, "get_cal_client", return_value=gc):
        result = _tool_forward_calendar_event(
            "EVENT1", ["Marc.Charest@amd.com"], expected_start="2026-09-14T12:30"
        )

    assert result["updated"] is False
    assert "date mismatch" in result["error"]
    gc.patch.assert_not_called()


def test_missing_graph_start_is_rejected_without_patch():
    gc = MagicMock()
    gc.get.return_value = _event(start={})
    with patch.object(m365_helpers, "get_cal_client", return_value=gc):
        result = _tool_forward_calendar_event(
            "EVENT1", ["Marc.Charest@amd.com"], expected_start="2026-09-14"
        )

    assert result["updated"] is False
    assert "start time" in result["error"]
    gc.patch.assert_not_called()


def test_patch_failure_never_falls_back_to_forward_email():
    gc = MagicMock()
    gc.get.return_value = _event()
    gc.patch.side_effect = RuntimeError("timeout")
    with patch.object(m365_helpers, "get_cal_client", return_value=gc):
        result = _tool_forward_calendar_event(
            "EVENT1", ["Marc.Charest@amd.com"], expected_start="2026-09-14"
        )

    assert result["updated"] is False
    assert "PATCH" in result["error"]
    gc.post.assert_not_called()


def test_verification_failure_never_falls_back_to_forward_email():
    gc = MagicMock()
    gc.get.side_effect = [_event(), RuntimeError("temporary Graph read failure")]
    with patch.object(m365_helpers, "get_cal_client", return_value=gc):
        result = _tool_forward_calendar_event(
            "EVENT1", ["Marc.Charest@amd.com"], expected_start="2026-09-14"
        )

    assert result["updated"] is False
    assert "verify" in result["error"]
    gc.post.assert_not_called()


def test_missing_verified_attendee_is_not_a_success():
    gc = MagicMock()
    gc.get.side_effect = [_event(), {"attendees": []}]
    with patch.object(m365_helpers, "get_cal_client", return_value=gc):
        result = _tool_forward_calendar_event(
            "EVENT1", ["Marc.Charest@amd.com"], expected_start="2026-09-14"
        )

    assert result["updated"] is False
    assert result["missing_attendees"] == ["Marc.Charest@amd.com"]


def test_expected_start_is_required_before_event_lookup():
    gc = MagicMock()
    with patch.object(m365_helpers, "get_cal_client", return_value=gc):
        result = _tool_forward_calendar_event("EVENT1", ["Marc.Charest@amd.com"])

    assert result["updated"] is False
    assert "Expected occurrence start" in result["error"]
    gc.get.assert_not_called()
