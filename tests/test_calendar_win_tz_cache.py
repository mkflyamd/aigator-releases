"""A failed mailbox-timezone lookup (Graph outage) must not pin calendar times to UTC until restart."""

import pytest

import skills.calendar.helpers as cal_helpers


class _Client:
    def __init__(self, result):
        self.result = result
        self.calls = 0

    def get(self, path):
        self.calls += 1
        if isinstance(self.result, Exception):
            raise self.result
        return self.result


@pytest.fixture(autouse=True)
def _reset_cache(monkeypatch):
    monkeypatch.setattr(cal_helpers, "_user_win_tz_cache", None)


def test_failed_lookup_returns_utc_but_is_not_cached(monkeypatch):
    client = _Client(RuntimeError("502 from Graph"))
    monkeypatch.setattr(cal_helpers, "get_cal_client", lambda: client)

    assert cal_helpers.get_user_win_tz() == "UTC"
    assert cal_helpers._user_win_tz_cache is None

    client.result = {"timeZone": "Pacific Standard Time"}
    assert cal_helpers.get_user_win_tz() == "Pacific Standard Time"


def test_successful_lookup_is_cached(monkeypatch):
    client = _Client({"timeZone": "Pacific Standard Time"})
    monkeypatch.setattr(cal_helpers, "get_cal_client", lambda: client)

    assert cal_helpers.get_user_win_tz() == "Pacific Standard Time"
    assert cal_helpers.get_user_win_tz() == "Pacific Standard Time"
    assert client.calls == 1


def test_missing_timezone_field_is_not_cached(monkeypatch):
    client = _Client({})
    monkeypatch.setattr(cal_helpers, "get_cal_client", lambda: client)

    assert cal_helpers.get_user_win_tz() == "UTC"
    assert cal_helpers._user_win_tz_cache is None


def test_null_settings_body_is_not_cached(monkeypatch):
    client = _Client(None)
    monkeypatch.setattr(cal_helpers, "get_cal_client", lambda: client)

    assert cal_helpers.get_user_win_tz() == "UTC"
    assert cal_helpers._user_win_tz_cache is None
