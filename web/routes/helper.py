"""Helper-process bridge for the native Slack adjacent-window variant.

Pure in-memory state — no DB, no file I/O. The browser page POSTs its outer
rect here; the Electron helper polls it to dock flush to the browser's right
edge. The helper POSTs Slack context here; Gator's frontend reads it to show
a context chip and feed the agent.

State resets on server restart — acceptable because the helper reconnects
within 200ms and re-posts context on the next URL change.
"""

import time
import threading
from fastapi import APIRouter

router = APIRouter()

_lock = threading.Lock()
_browser_rect = {"x": 0, "y": 0, "width": 0, "height": 0, "ts": 0}
_slack_ctx = {"team": None, "channel": None, "thread_ts": None, "ts": 0}
_active = False


@router.post("/api/helper/position")
async def helper_set_position(rect: dict):
    """Browser page reports its outer window rect (screen coords)."""
    global _browser_rect
    with _lock:
        _browser_rect = {
            "x": int(rect.get("x", 0)),
            "y": int(rect.get("y", 0)),
            "width": int(rect.get("width", 0)),
            "height": int(rect.get("height", 0)),
            "ts": int(time.time() * 1000),
        }
    return {"ok": True}


@router.get("/api/helper/position")
async def helper_get_position():
    """Helper reads the browser rect to dock itself to the right edge."""
    with _lock:
        return dict(_browser_rect)


@router.post("/api/helper/slack-ctx")
async def helper_set_slack_ctx(ctx: dict):
    """Helper reports current Slack context {team, channel, thread_ts}."""
    global _slack_ctx
    with _lock:
        _slack_ctx = {
            "team": ctx.get("team"),
            "channel": ctx.get("channel"),
            "thread_ts": ctx.get("thread_ts"),
            "ts": int(time.time() * 1000),
        }
    return {"ok": True}


@router.get("/api/helper/slack-ctx")
async def helper_get_slack_ctx():
    """Gator frontend reads current Slack context for the chip / agent."""
    with _lock:
        return dict(_slack_ctx)


@router.post("/api/helper/active")
async def helper_set_active(body: dict):
    """Gator frontend signals whether the helper should be visible."""
    global _active
    with _lock:
        _active = bool(body.get("active", False))
    return {"ok": True}


@router.get("/api/helper/active")
async def helper_get_active():
    """Helper polls this to know whether to show or hide itself."""
    with _lock:
        return {"active": _active}
