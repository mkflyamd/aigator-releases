"""Background task queue endpoints and notification stream."""

import asyncio as _asyncio
import json

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import StreamingResponse

from task_queue import enqueue, get_task, list_tasks, cancel_task, get_usage_summary
import shared

router = APIRouter()


@router.get("/api/notifications/stream")
async def notification_stream():
    q = shared.subscribe_notifications()
    async def _gen():
        try:
            yield "data: {\"type\": \"connected\"}\n\n"
            while True:
                try:
                    msg = await _asyncio.wait_for(q.get(), timeout=30)
                    yield f"data: {json.dumps(msg)}\n\n"
                except _asyncio.TimeoutError:
                    yield "data: {\"type\": \"ping\"}\n\n"
        finally:
            shared.unsubscribe_notifications(q)
    return StreamingResponse(_gen(), media_type="text/event-stream")


@router.post("/api/tasks")
async def create_task_endpoint(request: Request):
    body = await request.json()
    prompt = body.get("prompt", "").strip()
    if not prompt:
        raise HTTPException(400, "prompt required")
    task_id = await enqueue(prompt)
    return {"task_id": task_id, "status": "pending"}


@router.get("/api/tasks/summary")
async def tasks_summary():
    tasks = await list_tasks(limit=20)
    running = [t for t in tasks if t["status"] == "running"]
    recent_done = [t for t in tasks if t["status"] in ("done", "failed")][:5]
    return {
        "running_count": len(running),
        "recent": [{"task_id": t["task_id"], "status": t["status"],
                     "completed_at": t.get("completed_at"),
                     "result_preview": (t.get("result") or "")[:60]} for t in recent_done],
    }


@router.get("/api/tasks")
async def get_tasks_endpoint():
    return await list_tasks()


@router.get("/api/tasks/{task_id}")
async def get_task_status(task_id: str):
    task = await get_task(task_id)
    if not task:
        raise HTTPException(404, "task not found")
    # Re-seed conversation_store if empty — covers server restarts and tab closes.
    # This ensures "view this chat" follow-ups always have server-side history.
    ctx = task.get("context_id")
    result = task.get("result") or ""
    prompt = task.get("prompt") or ""
    if ctx and result and not shared.conversation_store.has(ctx):
        await shared.conversation_store.append(ctx, [
            {"role": "user", "content": prompt},
            {"role": "assistant", "content": result},
        ])
    return task


@router.post("/api/tasks/{task_id}/cancel")
async def cancel_task_endpoint(task_id: str):
    return {"cancelled": await cancel_task(task_id)}


@router.delete("/api/tasks/{task_id}")
async def delete_task(task_id: str):
    """Delete a single task by ID."""
    import aiosqlite
    from task_queue import DB_PATH
    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute("DELETE FROM tasks WHERE task_id = ?", (task_id,))
        await db.commit()
        if cur.rowcount == 0:
            raise HTTPException(404, "task not found")
        return {"deleted": True}


@router.get("/api/usage")
async def usage_summary():
    """Token usage summary: today + all time."""
    return await get_usage_summary()


@router.get("/api/browser/status")
async def browser_status():
    """Check if browser is active and/or paused."""
    import browser_agent as _ba
    return {
        "active": _ba.is_browser_active(),
        "paused": _ba.is_browser_paused(),
        "bot_block": _ba._bot_block_reason or "",
    }


@router.get("/api/browser/stream")
async def browser_stream():
    """SSE stream of browser step updates (screenshots + status)."""
    from browser_agent import is_browser_active, is_browser_paused, get_step_updates

    async def _gen():
        yield "data: {\"type\": \"connected\"}\n\n"
        cursor = 0
        while True:
            try:
                updates, cursor = get_step_updates(cursor)
                for update in updates:
                    yield f"data: {json.dumps({'type': 'step', **update})}\n\n"

                active = is_browser_active()
                paused = is_browser_paused()
                yield f"data: {json.dumps({'type': 'status', 'active': active, 'paused': paused})}\n\n"

                if not active and not updates:
                    yield "data: {\"type\": \"done\"}\n\n"
                    break

                await _asyncio.sleep(1.5)
            except Exception:
                break
    return StreamingResponse(_gen(), media_type="text/event-stream")


@router.post("/api/browser/pause")
async def browser_pause():
    """Pause the browser agent — user takes over."""
    from browser_agent import pause_browser, is_browser_active
    if not is_browser_active():
        raise HTTPException(400, "No browser task running")
    pause_browser()
    return {"paused": True}


@router.post("/api/browser/resume")
async def browser_resume():
    """Resume the browser agent — user hands back."""
    from browser_agent import resume_browser, is_browser_active
    if not is_browser_active():
        raise HTTPException(400, "No browser task running")
    resume_browser()
    return {"paused": False}


@router.post("/api/browser/cancel")
async def browser_cancel():
    """Cancel the running browser task."""
    from browser_agent import cancel_browser_task, is_browser_active
    cancel_browser_task()
    return {"cancelled": True}


@router.post("/api/browser/confirm/{confirm_id}")
async def browser_confirm_allow(confirm_id: str):
    """Allow a pending browser confirm gate."""
    from browser_agent import resolve_browser_confirm
    resolve_browser_confirm(confirm_id, allowed=True)
    return {"ok": True}


@router.post("/api/browser/confirm/{confirm_id}/cancel")
async def browser_confirm_cancel(confirm_id: str):
    """Cancel a pending browser confirm gate."""
    from browser_agent import resolve_browser_confirm
    resolve_browser_confirm(confirm_id, allowed=False)
    return {"ok": True}


@router.delete("/api/tasks/completed")
async def clear_completed_tasks():
    """Delete all completed (done/failed) tasks from the database."""
    import aiosqlite
    from task_queue import DB_PATH
    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute("DELETE FROM tasks WHERE status IN ('done', 'failed')")
        await db.commit()
        return {"deleted": cur.rowcount}
