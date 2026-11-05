from unittest.mock import patch

from fastapi.testclient import TestClient

from app import app
from security import get_csrf_token


def _post(path, body):
    return TestClient(app).post(path, headers={"X-CSRF-Token": get_csrf_token("testserver")}, json=body)


SLOT = {"start": "2026-11-10T09:00:00", "end": "2026-11-10T09:30:00", "timezone": "Pacific Standard Time"}


def test_slot_zones_groups_people_who_share_a_result():
    res = _post(
        "/api/calendar/slot-zones",
        {
            **SLOT,
            "zones": {
                "aswin@example.com": "Central Standard Time",
                "faisal@example.com": "GMT Standard Time",
                "tej@example.com": "Central Standard Time",
            },
        },
    )
    assert res.status_code == 200
    assert res.json() == [
        {"label": "11:00 AM – 11:30 AM CST", "people": ["aswin@example.com", "tej@example.com"]},
        {"label": "5:00 PM – 5:30 PM GMT", "people": ["faisal@example.com"]},
    ]


def test_slot_zones_leaves_out_the_grid_zone_and_unknown_zones():
    res = _post(
        "/api/calendar/slot-zones",
        {
            **SLOT,
            "zones": {
                "diwakar@example.com": "Pacific Standard Time",
                "nobody@example.com": "No Such Zone",
                "tej@example.com": "Central Standard Time",
            },
        },
    )
    assert res.json() == [{"label": "11:00 AM – 11:30 AM CST", "people": ["tej@example.com"]}]


def test_slot_zones_makes_no_graph_call():
    with patch("skills._m365.helpers.get_cal_client", side_effect=AssertionError("no Graph call")):
        res = _post("/api/calendar/slot-zones", {**SLOT, "zones": {"tej@example.com": "Central Standard Time"}})
    assert res.status_code == 200


def test_slot_zones_rejects_a_flood_of_people():
    zones = {f"p{n}@example.com": "Central Standard Time" for n in range(41)}
    assert _post("/api/calendar/slot-zones", {**SLOT, "zones": zones}).status_code == 400


def test_availability_days_passes_the_zones_flag_on():
    seen = {}

    def fake(emails, after_date, duration, count, dates, with_zones):
        seen["with_zones"] = with_zones
        return {"days": [], "zones": {}}

    with patch("skills.calendar.tools._tool_load_availability_days", side_effect=fake):
        res = _post(
            "/api/calendar/availability-days",
            {"emails": ["a@example.com"], "dates": ["2030-01-07"], "zones": True},
        )
    assert res.status_code == 200 and seen["with_zones"] is True
