"""Regression test for the "silent next message" bug.

Root cause (confirmed from a real server log): `chat_task_store.cancel()`
only set a `cancelled` flag and pushed a `__DONE__` SSE sentinel — it never
actually cancelled the background asyncio task running the turn. That task
kept holding `conversation_store.lock_for(context_id)` for as long as its
in-flight tool `await` took to finish (or the 300s timeout), so the *next*
message on the same context_id silently blocked at
`async with lock_for(context_id):` until the stuck turn eventually finished.

These tests exercise `ChatTaskStore` directly (no FastAPI app, no network)
using a real `asyncio.Lock` to simulate the per-context turn lock from
`web/conversation_store.py`.
"""
import asyncio
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).parent.parent / "web"))

from chat_task_store import ChatTaskStore


async def test_cancel_releases_lock_promptly():
    """The key regression test: cancelling a task must release the lock it
    holds almost immediately, not only once its stuck await finally resolves.
    """
    store = ChatTaskStore()
    task_id = "task-1"
    context_id = "ctx-1"
    store.create_task(task_id, context_id)

    lock = asyncio.Lock()
    never_completes: asyncio.Future = asyncio.get_event_loop().create_future()

    async def _run_turn():
        async with lock:
            # Simulates a stuck tool call (e.g. a slow browser action) that
            # never returns on its own — only cancellation should unblock it.
            await never_completes

    bg_task = asyncio.create_task(_run_turn())
    store.track_task(task_id, bg_task)

    # Let the background task actually start and acquire the lock.
    for _ in range(20):
        if lock.locked():
            break
        await asyncio.sleep(0)
    assert lock.locked(), "background task should hold the lock while 'stuck'"

    # A second turn on the same context must currently be blocked.
    second_turn_acquired = asyncio.Event()

    async def _second_turn():
        async with lock:
            second_turn_acquired.set()

    second_task = asyncio.create_task(_second_turn())
    await asyncio.sleep(0)
    assert not second_turn_acquired.is_set(), "second turn must be blocked while first holds the lock"

    # Cancel the first (stuck) turn.
    cancelled = store.cancel(task_id)
    assert cancelled is True

    # The lock must be released PROMPTLY (not after some long/never timeout).
    await asyncio.wait_for(second_turn_acquired.wait(), timeout=2.0)

    assert bg_task.cancelled()

    # Clean up: don't let "Task exception was never retrieved" leak from the test.
    second_task.cancel()
    try:
        await second_task
    except asyncio.CancelledError:
        pass


async def test_cancel_cancels_stored_asyncio_task_and_notifies_subscriber():
    store = ChatTaskStore()
    task_id = "task-2"
    context_id = "ctx-2"
    store.create_task(task_id, context_id)

    started = asyncio.Event()

    async def _run_turn():
        started.set()
        await asyncio.sleep(1000)

    bg_task = asyncio.create_task(_run_turn())
    store.track_task(task_id, bg_task)
    await started.wait()

    q = store.subscribe(task_id)
    assert q is not None

    cancelled = store.cancel(task_id)
    assert cancelled is True
    assert store.is_cancelled(task_id) is True

    # __DONE__ sentinel must still reach subscribers.
    sentinel = await asyncio.wait_for(q.get(), timeout=2.0)
    assert sentinel == "__DONE__"

    # The underlying asyncio task must actually be cancelled.
    with contextlib_suppress_cancelled():
        await asyncio.wait_for(bg_task, timeout=2.0)
    assert bg_task.cancelled()


def contextlib_suppress_cancelled():
    import contextlib
    return contextlib.suppress(asyncio.CancelledError)


async def test_cancel_unknown_or_done_task_is_safe_noop():
    store = ChatTaskStore()

    # Unknown task_id.
    assert store.cancel("does-not-exist") is False

    # Already-done task.
    store.create_task("task-3", "ctx-3")
    store.mark_done("task-3")
    assert store.cancel("task-3") is False


async def test_cancelled_task_exception_is_retrieved_cleanly():
    """After cancel(), awaiting the stored task must raise CancelledError
    (not silently swallow it) but nothing should be left un-retrieved on the
    task itself — i.e. the done-callback used by track_task must not leave
    an unretrieved CancelledError that asyncio logs as
    'Task exception was never retrieved'.
    """
    store = ChatTaskStore()
    task_id = "task-4"
    store.create_task(task_id, "ctx-4")

    started = asyncio.Event()

    async def _run_turn():
        started.set()
        await asyncio.sleep(1000)

    bg_task = asyncio.create_task(_run_turn())
    store.track_task(task_id, bg_task)
    await started.wait()

    store.cancel(task_id)

    raised = False
    try:
        await asyncio.wait_for(bg_task, timeout=2.0)
    except asyncio.CancelledError:
        raised = True
    assert raised
    assert bg_task.cancelled()

    # Give the done-callback a tick to run.
    await asyncio.sleep(0)
