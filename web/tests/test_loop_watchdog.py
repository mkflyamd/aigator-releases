"""A blocked event loop must be reported with the stack that blocks it."""

import asyncio
import logging
import time

import loop_watchdog


def _blocking_call_under_test():
    time.sleep(1.2)


def test_a_blocked_loop_is_logged_with_the_blocking_stack(caplog):
    async def run():
        stop = loop_watchdog.start(asyncio.get_running_loop(), threshold=0.4, interval=0.1)
        await asyncio.sleep(0.3)
        _blocking_call_under_test()
        await asyncio.sleep(0.3)
        stop.set()

    with caplog.at_level(logging.ERROR, logger="loop_watchdog"):
        asyncio.run(run())
    text = "\n".join(r.getMessage() for r in caplog.records)
    assert "event loop blocked" in text and "_blocking_call_under_test" in text


def test_a_healthy_loop_logs_nothing(caplog):
    async def run():
        stop = loop_watchdog.start(asyncio.get_running_loop(), threshold=0.4, interval=0.1)
        for _ in range(8):
            await asyncio.sleep(0.1)
        stop.set()

    with caplog.at_level(logging.ERROR, logger="loop_watchdog"):
        asyncio.run(run())
    assert not caplog.records
