"""cancel_task() must actually interrupt an already-RUNNING task, not just
a still-queued one.

Bug: the original cancel_task() only did `UPDATE tasks SET status=
'cancelled' WHERE ... AND status='pending'` — the instant a task flipped
to 'running' (worker() picked it up), Cancel silently did nothing at all,
forever, with no error shown, until the task finished or crashed on its
own. Root cause: worker() awaited _run_task(...) directly inline inside
its own single long-lived task, so there was no separate, individually-
cancellable asyncio.Task per background job to cancel in the first place.

Fix mirrors the mechanism interactive chat already uses for the same
problem (chat_task_store.cancel(): actually cancel the underlying
asyncio.Task, which raises CancelledError at its current await point).
"""
import asyncio
import json

import pytest


def _fresh_db(tmp_path):
    return tmp_path / "tasks.db"


def _run(coro):
    return asyncio.new_event_loop().run_until_complete(coro)


def _make_hanging_run_fn(started: "asyncio.Event", reached_unreachable: "list"):
    async def _run_fn(prompt, skills=None):
        yield f"data: {json.dumps({'text': 'partial output before the hang'})}\n\n"
        started.set()
        await asyncio.sleep(100)  # would hang "forever" without cancellation
        reached_unreachable.append(True)  # must never execute if cancel worked
        yield f"data: {json.dumps({'text': 'unreachable'})}\n\n"

    return _run_fn


@pytest.fixture
def tq(tmp_path, monkeypatch):
    import task_queue as _tq

    monkeypatch.setattr(_tq, "DB_PATH", _fresh_db(tmp_path))
    return _tq


def test_cancel_interrupts_an_already_running_task(tq):
    reached_unreachable: list = []

    async def _scenario():
        await tq.init_db()
        task_id = await tq.enqueue("do something slow")

        started = asyncio.Event()
        run_fn = _make_hanging_run_fn(started, reached_unreachable)
        worker_task = asyncio.create_task(tq.worker(run_fn))
        try:
            await asyncio.wait_for(started.wait(), timeout=3)
            # The task must now be tracked as genuinely running, not just
            # queued — this is exactly the state the old cancel_task()
            # could never reach into.
            row_while_running = await tq.get_task(task_id)
            assert row_while_running["status"] == "running"
            assert task_id in tq._RUNNING_TASKS

            cancelled = await tq.cancel_task(task_id)
            assert cancelled is True

            for _ in range(100):
                row = await tq.get_task(task_id)
                if row["status"] == "cancelled":
                    return row
                await asyncio.sleep(0.02)
            pytest.fail("task never reached status='cancelled' after cancel_task()")
        finally:
            worker_task.cancel()
            try:
                await worker_task
            except asyncio.CancelledError:
                pass

    row = _run(_scenario())
    assert row["status"] == "cancelled"
    assert row["result"] == "Cancelled by user."
    assert not reached_unreachable, (
        "code after the cancellation point ran — the task was not actually "
        "interrupted, just relabeled after the fact"
    )
    assert task_id_not_leaked_in_running_tasks(tq)


def task_id_not_leaked_in_running_tasks(tq) -> bool:
    return len(tq._RUNNING_TASKS) == 0


def test_cancel_still_works_for_a_still_pending_task(tq):
    """Preserves the original, already-correct behavior: a task that
    hasn't started running yet can still be cancelled before the worker
    ever picks it up."""

    async def _scenario():
        await tq.init_db()
        task_id = await tq.enqueue("never actually runs")
        cancelled = await tq.cancel_task(task_id)
        row = await tq.get_task(task_id)
        return cancelled, row

    cancelled, row = _run(_scenario())
    assert cancelled is True
    assert row["status"] == "cancelled"


def test_cancel_unknown_task_returns_false(tq):
    async def _scenario():
        await tq.init_db()
        return await tq.cancel_task("does-not-exist")

    assert _run(_scenario()) is False


def test_cancel_already_done_task_returns_false(tq):
    async def _run_fn(prompt, skills=None):
        yield f"data: {json.dumps({'text': 'done fast'})}\n\n"
        yield "data: [DONE]\n\n"

    async def _scenario():
        await tq.init_db()
        task_id = await tq.enqueue("finishes immediately")
        await tq._run_task(task_id, "finishes immediately", _run_fn)
        return await tq.cancel_task(task_id)

    assert _run(_scenario()) is False


def test_worker_loop_survives_a_cancel_and_processes_the_next_task(tq):
    """The whole point of wrapping _run_task in its own asyncio.Task,
    tracked separately from the worker loop's own task: cancelling one job
    must not kill background-task processing entirely — the worker must
    carry on and pick up the next pending task normally afterward."""

    async def _scenario():
        await tq.init_db()
        slow_task_id = await tq.enqueue("slow one")
        fast_task_id = await tq.enqueue("fast one")

        started = asyncio.Event()
        call_count = {"n": 0}

        async def _run_fn(prompt, skills=None):
            call_count["n"] += 1
            if call_count["n"] == 1:
                yield f"data: {json.dumps({'text': 'partial'})}\n\n"
                started.set()
                await asyncio.sleep(100)
            else:
                yield f"data: {json.dumps({'text': 'the fast one finished'})}\n\n"
                yield "data: [DONE]\n\n"

        worker_task = asyncio.create_task(tq.worker(_run_fn))
        try:
            await asyncio.wait_for(started.wait(), timeout=3)
            await tq.cancel_task(slow_task_id)

            for _ in range(150):
                row = await tq.get_task(fast_task_id)
                if row["status"] == "done":
                    return row
                await asyncio.sleep(0.02)
            pytest.fail("worker never processed the second task after cancelling the first")
        finally:
            worker_task.cancel()
            try:
                await worker_task
            except asyncio.CancelledError:
                pass

    row = _run(_scenario())
    assert row["status"] == "done"
    assert row["result"] == "the fast one finished"
