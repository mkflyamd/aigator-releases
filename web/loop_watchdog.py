"""Reports when the asyncio event loop is blocked, with the stack that is blocking it.

A blocking call inside an async handler freezes every request (status polls, Stop, model switching).
The loop cannot report its own stall, so a separate thread watches a heartbeat the loop keeps updating.
"""

import logging
import sys
import threading
import time
import traceback

_log = logging.getLogger(__name__)


def start(loop, *, threshold: float = 3.0, interval: float = 1.0) -> threading.Event:
    """Call from the loop's own thread. Logs one error per stall longer than `threshold` seconds; set the returned event to stop watching."""
    loop_thread = threading.get_ident()
    stop = threading.Event()
    state = {"beat": time.monotonic()}

    def _beat():
        state["beat"] = time.monotonic()
        loop.call_later(interval, _beat)

    loop.call_soon(_beat)

    def _watch():
        reported = False
        while not stop.wait(interval):
            lag = time.monotonic() - state["beat"]
            if lag <= threshold:
                reported = False
                continue
            if reported:
                continue
            reported = True
            frame = sys._current_frames().get(loop_thread)
            stack = "".join(traceback.format_stack(frame)) if frame else "(unavailable)"
            _log.error("[loop-watchdog] event loop blocked for %.1fs. Blocking stack:\n%s", lag, stack)

    threading.Thread(target=_watch, name="loop-watchdog", daemon=True).start()
    return stop
