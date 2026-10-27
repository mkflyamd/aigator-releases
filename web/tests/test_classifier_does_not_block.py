"""A stalled gateway call in the skill classifier froze the whole event loop (every request, Stop
included) until the SDK timeout, leaving the UI on the 3-dot indicator. It must stay off the loop and
give up quickly."""

import asyncio
import threading
import time

import app  # noqa: F401 — populates registries
import httpx
from routes import chat


def test_a_hung_classifier_neither_blocks_the_loop_nor_the_turn(monkeypatch):
    release = threading.Event()
    monkeypatch.setattr(chat, "_CLASSIFY_TIMEOUT_S", 0.5)
    monkeypatch.setattr(chat, "_classify_skills_via_llm", lambda *a, **k: release.wait(30) or [])

    async def run():
        ticks = []

        async def heartbeat():
            while True:
                ticks.append(time.time())
                await asyncio.sleep(0.05)

        beat = asyncio.create_task(heartbeat())
        transport = httpx.ASGITransport(app=app.app)
        started = time.time()
        try:
            async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
                r = await client.post(
                    "/api/chat",
                    json={"message": "hi", "history": [], "context_id": "hung-classifier", "active_skills": []},
                )
            elapsed = time.time() - started
        finally:
            beat.cancel()
            release.set()
        return r, elapsed, ticks

    r, elapsed, ticks = asyncio.run(run())
    assert r.status_code == 200 and r.json().get("task_id")
    assert elapsed < 10
    assert max(b - a for a, b in zip(ticks, ticks[1:])) < 1.0, "the event loop was blocked"
