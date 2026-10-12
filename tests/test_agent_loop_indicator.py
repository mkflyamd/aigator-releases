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

    tc = SimpleNamespace(name="run_python", inputs={}, id="test-call-1")
    events = _collect(_build_runner(fake_execute), tc)
    statuses = [e for e in events if e.get("kind") == "status"]
    assert statuses == []


def test_running_indicator_emitted_on_successful_call():
    async def fake_execute(name, inputs, **kw):
        return {"result": "ok"}

    tc = SimpleNamespace(name="run_python", inputs={"code": "print(1)"}, id="test-call-2")
    events = _collect(_build_runner(fake_execute), tc)
    statuses = [e for e in events if e.get("kind") == "status"]
    assert any(e["status"] == "Running code..." for e in statuses)


def test_draft_event_lists_the_sources_read_earlier_in_the_turn(monkeypatch):
    import shared

    monkeypatch.setitem(shared.SKILL_TOOLS_MAP, "jira", ["jira_get_issue"])
    monkeypatch.setitem(shared.SKILL_TOOLS_MAP, "slack", ["slack_draft"])

    async def fake_execute(name, inputs, **kw):
        if name == "slack_draft":
            return {"_draft": "slack-post", "data": {"draft_id": "d1"}}
        return {"result": "ok"}

    run_tool_block = _build_runner(fake_execute)

    async def _go():
        q = asyncio.Queue()
        await run_tool_block(SimpleNamespace(name="jira_get_issue", inputs={}, id="c1"), q)
        await run_tool_block(SimpleNamespace(name="slack_draft", inputs={}, id="c2"), q)
        return [q.get_nowait() for _ in range(q.qsize())]

    loop = asyncio.new_event_loop()
    try:
        events = loop.run_until_complete(_go())
    finally:
        loop.close()
        asyncio.set_event_loop(asyncio.new_event_loop())
    draft = next(e for e in events if e.get("kind") == "draft")
    assert draft["data"]["sources"] == ["Jira"]
    assert draft["data"]["draft_id"] == "d1"


def _run_two_calls(monkeypatch, tmp_path, policy_text):
    import shared
    from sandbox import policy as pol

    policy_file = tmp_path / "sandbox-policy.json"
    if policy_text is not None:
        policy_file.write_text(policy_text, encoding="utf-8")
    monkeypatch.setattr(pol, "policy_path", lambda: policy_file)
    pol._reset_cache()
    monkeypatch.setitem(shared.SKILL_TOOLS_MAP, "jira", ["jira_get_issue"])
    monkeypatch.setitem(shared.SKILL_TOOLS_MAP, "slack", ["slack_draft"])

    async def fake_execute(name, inputs, **kw):
        if name == "slack_draft":
            from skills._drafts import create_draft
            draft_id = create_draft("slack-post", {}, {})
            return {"_draft": "slack-post", "data": {"draft_id": draft_id, "body": "This is Confidential"}}
        return {"result": "ok"}

    run_tool_block = _build_runner(fake_execute)

    async def _go():
        q = asyncio.Queue()
        await run_tool_block(SimpleNamespace(name="jira_get_issue", inputs={}, id="c1"), q)
        await run_tool_block(SimpleNamespace(name="slack_draft", inputs={}, id="c2"), q)
        return [q.get_nowait() for _ in range(q.qsize())]

    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(_go())
    finally:
        loop.close()
        asyncio.set_event_loop(asyncio.new_event_loop())
        pol._reset_cache()


def test_blocked_data_flow_refuses_the_draft_and_removes_it(monkeypatch, tmp_path):
    from skills import _drafts

    _drafts._pending_drafts.clear()
    events = _run_two_calls(monkeypatch, tmp_path, '{"blocked_data_flows": ["jira>slack"]}')
    assert not [e for e in events if e.get("kind") == "draft"]
    assert not _drafts._pending_drafts
    assert [e for e in events if e.get("kind") == "tool_result" and e["status"] == "error"]


def test_other_flows_still_produce_a_draft_with_a_sensitivity_tag(monkeypatch, tmp_path):
    events = _run_two_calls(monkeypatch, tmp_path, '{"blocked_data_flows": ["jira>email", "email>slack"]}')
    draft = next(e for e in events if e.get("kind") == "draft")
    assert draft["data"]["sensitive"] == ["Confidential"]
