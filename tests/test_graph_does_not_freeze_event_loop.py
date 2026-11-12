"""While a Microsoft Graph call is stuck, unrelated requests must still be answered promptly."""

import asyncio
import pathlib
import sys
import threading
import time

sys.path.insert(0, str(pathlib.Path(__file__).parent.parent / "web"))

import httpx

from app import app

SLOW_GRAPH_SECONDS = 2.0


class _SlowGraph:
    def get(self, *args, **kwargs):
        time.sleep(SLOW_GRAPH_SECONDS)
        return {"value": [], "timeZone": "UTC"}


async def test_slow_graph_call_does_not_block_other_requests(monkeypatch):
    import skills._m365.helpers as m365_helpers

    monkeypatch.setattr(m365_helpers, "get_cal_client", lambda: _SlowGraph())
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        slow = asyncio.create_task(
            client.get("/api/calendar/events", params={"start": "2026-11-01", "end": "2026-11-02"})
        )
        await asyncio.sleep(0.3)
        started = time.monotonic()
        fast = await client.get("/api/config/model/status")
        fast_elapsed = time.monotonic() - started

        assert not slow.done(), "the slow Graph call finished early; the test is not exercising a blocked call"
        assert fast.status_code == 200
        assert fast_elapsed < SLOW_GRAPH_SECONDS / 2, f"event loop was blocked for {fast_elapsed:.2f}s"
        assert (await slow).status_code == 200
