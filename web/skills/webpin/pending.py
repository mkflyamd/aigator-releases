"""In-memory registry of recapture requests awaiting a browser round trip."""
from __future__ import annotations

import asyncio
import uuid

_pending: dict[str, dict] = {}


def create(pin_id: str, context_id: str) -> tuple[str, asyncio.Future]:
    loop = asyncio.get_running_loop()
    request_id = uuid.uuid4().hex
    fut = loop.create_future()
    _pending[request_id] = {"pin_id": pin_id, "context_id": context_id, "future": fut, "loop": loop, "claimed": False}
    return request_id, fut


def claim(request_id: str, pin_id: str) -> bool:
    entry = _pending.get(request_id)
    if not entry or entry["pin_id"] != pin_id or entry["claimed"]:
        return False
    entry["claimed"] = True
    return True


def finish(request_id: str, result: dict) -> None:
    entry = _pending.get(request_id)
    if entry:
        fut = entry["future"]
        entry["loop"].call_soon_threadsafe(lambda: fut.done() or fut.set_result(result))


def resolve(request_id: str, pin_id: str, result: dict) -> str:
    if not claim(request_id, pin_id):
        return "conflict"
    finish(request_id, result)
    return "ok"


def discard(request_id: str) -> None:
    _pending.pop(request_id, None)
