"""A burst of slow Graph calls must not use up the threadpool: static files are still served."""

import asyncio
import pathlib
import sys
import threading
import time

sys.path.insert(0, str(pathlib.Path(__file__).parent.parent / "web"))

import httpx

from app import app

SLOW_GRAPH_SECONDS = 2.0
BURST = 80


class _SlowPool:
    def __init__(self):
        self.in_flight = 0
        self.peak = 0
        self._lock = threading.Lock()

    def request(self, method, url, **kw):
        with self._lock:
            self.in_flight += 1
            self.peak = max(self.peak, self.in_flight)
        try:
            time.sleep(SLOW_GRAPH_SECONDS)
        finally:
            with self._lock:
                self.in_flight -= 1
        return httpx.Response(
            200, json={"value": [], "timeZone": "UTC"}, request=httpx.Request(method, url)
        )


async def test_burst_of_slow_graph_calls_leaves_threads_for_static_files(monkeypatch):
    import skills._m365.helpers as m365_helpers
    import skills.calendar.helpers as cal_helpers

    pool = _SlowPool()
    graph_client_cls = m365_helpers._load_graph_client_class()
    monkeypatch.setitem(graph_client_cls._request.__globals__, "_get_http_pool", lambda: pool)
    gc = graph_client_cls.__new__(graph_client_cls)
    gc._access_token = "aigator-fake-api-key"
    gc._expires_at = 1e12
    monkeypatch.setattr(gc, "_headers", lambda: {})
    monkeypatch.setattr(cal_helpers, "_user_win_tz_cache", None)
    monkeypatch.setattr(m365_helpers, "get_cal_client", lambda: gc)
    monkeypatch.setattr(cal_helpers, "get_cal_client", lambda: gc)

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        burst = [
            asyncio.create_task(
                client.get("/api/calendar/events", params={"start": "2026-11-01", "end": "2026-11-02"})
            )
            for _ in range(BURST)
        ]
        await asyncio.sleep(0.5)
        started = time.monotonic()
        static = await client.get("/static/style.css")
        static_elapsed = time.monotonic() - started
        busy_with_graph = pool.in_flight
        await asyncio.gather(*burst)

    assert static.status_code == 200
    assert static_elapsed < SLOW_GRAPH_SECONDS / 2, f"static file waited {static_elapsed:.2f}s behind Graph calls"
    assert busy_with_graph > 0, "no Graph call was in flight; the test is not exercising a slow Graph"
    assert pool.peak <= 24, f"{pool.peak} Graph calls were in flight at once"
