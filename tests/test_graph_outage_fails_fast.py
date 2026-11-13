"""A Graph outage must not hold a chat turn for minutes.

After a read exhausts its retries on 502/503/504, the same endpoint fails immediately for a short
cooldown, and a single call stops retrying once its time budget is spent.
"""

import importlib.util
from pathlib import Path

import httpx
import pytest

SRC = Path(__file__).resolve().parents[1] / "web" / "skills" / "m365-email" / "graph_client.py"
_spec = importlib.util.spec_from_file_location("graph_client_outage_under_test", SRC)
gcm = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(gcm)
GraphAPIError = gcm.GraphAPIError
GraphClient = gcm.GraphClient


def _response(status: int) -> httpx.Response:
    return httpx.Response(status, request=httpx.Request("GET", gcm.GRAPH_BASE + "/x"))


class _Pool:
    def __init__(self, statuses):
        self.statuses = list(statuses)
        self.calls = 0

    def request(self, method, url, **kw):
        self.calls += 1
        return _response(self.statuses.pop(0) if self.statuses else 200)


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setattr(gcm.time, "sleep", lambda s: None)
    gcm._reset_outage_state()
    gc = GraphClient.__new__(GraphClient)
    gc._access_token = "aigator-fake-api-key"
    gc._expires_at = 1e12
    monkeypatch.setattr(gc, "_headers", lambda: {})
    return gc


def _use(monkeypatch, pool):
    monkeypatch.setattr(gcm, "_get_http_pool", lambda: pool)


URL = gcm.GRAPH_BASE + "/me/mailFolders/inbox/messages?$top=10"


def test_repeat_read_after_exhausted_retries_fails_without_a_request(client, monkeypatch):
    pool = _Pool([502, 502, 502])
    _use(monkeypatch, pool)
    with pytest.raises(GraphAPIError):
        client._request("GET", URL, label="/me/mailFolders/inbox/messages")
    assert pool.calls == 3

    with pytest.raises(GraphAPIError) as err:
        client._request("GET", URL, label="/me/mailFolders/inbox/messages")
    assert pool.calls == 3, "cooldown must skip the network"
    assert "do not call" in str(err.value).lower()
    assert err.value.status_code == 503


def test_cooldown_is_per_endpoint(client, monkeypatch):
    pool = _Pool([502, 502, 502, 200])
    _use(monkeypatch, pool)
    with pytest.raises(GraphAPIError):
        client._request("GET", URL, label="inbox")
    client._request("GET", gcm.GRAPH_BASE + "/me/events", label="events")
    assert pool.calls == 4


def test_cooldown_expires(client, monkeypatch):
    pool = _Pool([502, 502, 502, 200])
    _use(monkeypatch, pool)
    now = [1000.0]
    monkeypatch.setattr(gcm.time, "monotonic", lambda: now[0])
    with pytest.raises(GraphAPIError):
        client._request("GET", URL, label="inbox")
    now[0] += gcm._OUTAGE_COOLDOWN_S + 1
    client._request("GET", URL, label="inbox")
    assert pool.calls == 4


def test_success_clears_cooldown(client, monkeypatch):
    pool = _Pool([502, 200])
    _use(monkeypatch, pool)
    client._request("GET", URL, label="inbox")
    assert pool.calls == 2
    client._request("GET", URL, label="inbox")
    assert pool.calls == 3


def test_mutating_requests_are_never_short_circuited(client, monkeypatch):
    pool = _Pool([502, 502, 502, 200])
    _use(monkeypatch, pool)
    with pytest.raises(GraphAPIError):
        client._request("GET", URL, label="inbox")
    client._request("POST", URL, label="inbox")
    assert pool.calls == 4


def test_client_error_does_not_start_a_cooldown(client, monkeypatch):
    pool = _Pool([404, 200])
    _use(monkeypatch, pool)
    with pytest.raises(GraphAPIError):
        client._request("GET", URL, label="inbox")
    client._request("GET", URL, label="inbox")
    assert pool.calls == 2


def test_retries_stop_when_the_time_budget_is_spent(client, monkeypatch):
    now = [0.0]
    monkeypatch.setattr(gcm.time, "monotonic", lambda: now[0])

    class SlowPool(_Pool):
        def request(self, method, url, **kw):
            now[0] += gcm._RETRY_BUDGET_S  # each attempt alone uses the whole budget
            return super().request(method, url, **kw)

    pool = SlowPool([502, 502, 502])
    _use(monkeypatch, pool)
    with pytest.raises(GraphAPIError):
        client._request("GET", URL, label="inbox")
    assert pool.calls == 1
