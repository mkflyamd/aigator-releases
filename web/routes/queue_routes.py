"""Queued chat messages: the chips under the composer. Sending is the chat route's job, not this one's."""

import asyncio

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

import shared
from chat_queue import QueueError, get_queue
from security import verify_csrf

router = APIRouter()


class QueueAdd(BaseModel):
    context_id: str
    id: str
    payload: dict


class QueueEdit(BaseModel):
    context_id: str
    text: str


class QueueContext(BaseModel):
    context_id: str


def _http(exc: QueueError) -> HTTPException:
    return HTTPException(status_code=exc.status, detail=exc.message)


@router.get("/api/queue")
def queue_snapshot(context_id: str):
    try:
        return {"ok": True, **get_queue().snapshot(context_id)}
    except QueueError as exc:
        raise _http(exc) from exc


@router.get("/api/queue/head")
async def queue_head(context_id: str):
    """The next message to send, or null while the queue is paused or empty, or a reply is still running.

    `live` tells the browser the null is only "not yet": the turn is still finishing, so ask again shortly.
    A reply the user just stopped does not count: it is being unwound, and the send that follows waits for it.
    """
    live = shared.chat_task_store.active_task_for(context_id)
    if live and not shared.chat_task_store.is_cancelled(live):
        return {"ok": True, "item": None, "live": True}
    try:
        return {"ok": True, "item": await asyncio.to_thread(get_queue().head, context_id)}
    except QueueError as exc:
        raise _http(exc) from exc


@router.post("/api/queue", dependencies=[Depends(verify_csrf)])
def queue_add(body: QueueAdd):
    try:
        get_queue().enqueue(body.context_id, body.id, body.payload)
        return {"ok": True, **get_queue().snapshot(body.context_id)}
    except QueueError as exc:
        raise _http(exc) from exc


@router.put("/api/queue/{item_id}", dependencies=[Depends(verify_csrf)])
def queue_edit(item_id: str, body: QueueEdit):
    try:
        get_queue().edit(body.context_id, item_id, body.text)
        return {"ok": True, **get_queue().snapshot(body.context_id)}
    except QueueError as exc:
        raise _http(exc) from exc


@router.delete("/api/queue/{item_id}", dependencies=[Depends(verify_csrf)])
def queue_remove(item_id: str, context_id: str):
    try:
        get_queue().remove(context_id, item_id)
        return {"ok": True, **get_queue().snapshot(context_id)}
    except QueueError as exc:
        raise _http(exc) from exc


@router.post("/api/queue/resume", dependencies=[Depends(verify_csrf)])
def queue_resume(body: QueueContext):
    try:
        get_queue().resume(body.context_id)
        return {"ok": True, **get_queue().snapshot(body.context_id)}
    except QueueError as exc:
        raise _http(exc) from exc


@router.post("/api/queue/clear", dependencies=[Depends(verify_csrf)])
def queue_clear(body: QueueContext):
    try:
        get_queue().clear(body.context_id)
        return {"ok": True, **get_queue().snapshot(body.context_id)}
    except QueueError as exc:
        raise _http(exc) from exc
