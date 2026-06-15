"""Issue #25 (crit. 3): the chat UI showed a phantom "Running code..." indicator
even when the tool call was rejected for missing required args (truncated payload).

The status indicator must not be emitted when execute_tool rejects a call before
running it, so the user sees at most one indicator per real execution.
"""
import asyncio
import sys
import pathlib
from types import SimpleNamespace

sys.path.insert(0, str(pathlib.Path(__file__).parent.parent / "web"))

from agent_loop import _make_tool_runner

TOOL_STATUS = {"run_python": "Running code..."}


def _build_runner(fake_execute):
    run_tool_block, _, _ = _make_tool_runner(
        fake_execute, set(), TOOL_STATUS, lambda name, result: None, "__slack_safe__"
    )
    return run_tool_block


def _collect(run_tool_block, tc):
    async def _go():
        q = asyncio.Queue()
        await run_tool_block(tc, q)
        events = []
        while not q.empty():
            events.append(q.get_nowait())
        return events

    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(_go())
    finally:
        loop.close()
        # asyncio.run / closing a loop leaves no current loop; restore one so
        # sibling tests using the (deprecated) get_event_loop() pattern still work.
        asyncio.set_event_loop(asyncio.new_event_loop())


def test_no_running_indicator_when_call_rejected_for_missing_args():
    async def fake_execute(name, inputs, **kw):
        return {"error": "missing_required_params", "tool": name, "missing": ["code"]}

    tc = SimpleNamespace(name="run_python", inputs={})
    events = _collect(_build_runner(fake_execute), tc)
    statuses = [e for e in events if e.get("kind") == "status"]
    assert statuses == []


def test_running_indicator_emitted_on_successful_call():
    async def fake_execute(name, inputs, **kw):
        return {"result": "ok"}

    tc = SimpleNamespace(name="run_python", inputs={"code": "print(1)"})
    events = _collect(_build_runner(fake_execute), tc)
    statuses = [e for e in events if e.get("kind") == "status"]
    assert any(e["status"] == "Running code..." for e in statuses)
