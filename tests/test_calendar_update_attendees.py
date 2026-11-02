"""update_calendar_event must not drop the attendee type the caller left out.

Graph replaces the whole attendees array on PATCH, so adding one required
attendee used to silently remove every optional attendee from the event.
"""
from unittest.mock import MagicMock, patch

from skills._m365 import helpers as m365_helpers
from skills.calendar.tools import _tool_update_calendar_event


def _person(address, kind, name=""):
    return {"emailAddress": {"address": address, "name": name or address}, "type": kind, "status": {"response": "none"}}


CURRENT = [
    _person("req@example.com", "required"),
    _person("opt1@example.com", "optional"),
    _person("opt2@example.com", "optional"),
    _person("room@example.com", "resource"),
]


def _update(**kwargs):
    gc = MagicMock()
    gc.get.return_value = {"attendees": CURRENT, "subject": "Sync"}
    with patch.object(m365_helpers, "get_cal_client", return_value=gc):
        result = _tool_update_calendar_event("EVENT1", **kwargs)
    return result, gc


def _sent(gc):
    return {(a["emailAddress"]["address"], a["type"]) for a in gc.patch.call_args.args[1]["attendees"]}


def test_adding_a_required_attendee_keeps_the_optional_ones_and_the_room():
    result, gc = _update(attendees=["req@example.com", "new@example.com"])
    assert result["updated"] is True
    assert _sent(gc) == {
        ("req@example.com", "required"),
        ("new@example.com", "required"),
        ("opt1@example.com", "optional"),
        ("opt2@example.com", "optional"),
        ("room@example.com", "resource"),
    }


def test_replacing_the_optional_list_keeps_the_required_ones():
    _, gc = _update(optional_attendees=["opt3@example.com"])
    assert _sent(gc) == {
        ("req@example.com", "required"),
        ("opt3@example.com", "optional"),
        ("room@example.com", "resource"),
    }


def test_moving_someone_between_lists_does_not_duplicate_them():
    _, gc = _update(attendees=["req@example.com", "opt1@example.com"])
    sent = gc.patch.call_args.args[1]["attendees"]
    assert [a["emailAddress"]["address"] for a in sent].count("opt1@example.com") == 1
    assert ("opt1@example.com", "required") in _sent(gc)


def test_an_update_without_attendees_does_not_touch_them_or_read_them():
    _, gc = _update(subject="New title")
    assert "attendees" not in gc.patch.call_args.args[1]


def test_if_the_current_attendees_cannot_be_read_nothing_is_sent():
    gc = MagicMock()
    gc.get.side_effect = RuntimeError("boom")
    with patch.object(m365_helpers, "get_cal_client", return_value=gc):
        result = _tool_update_calendar_event("EVENT1", attendees=["new@example.com"])
    assert result["updated"] is False
    gc.patch.assert_not_called()
