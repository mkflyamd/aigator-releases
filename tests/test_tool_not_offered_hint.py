"""A call to a tool that is not offered this turn must tell the model how to get it
(request_skill for the owning skill) instead of leaving it to guess or give up."""

import asyncio
from types import SimpleNamespace

import app  # noqa: F401 — importing populates the skill registries at startup
import shared
from agent_loop import _make_tool_runner, _not_offered_hint


def _runner_tool():
    for sid in ("shell_runner", "code_runner"):
        tools = shared.SKILL_TOOLS_MAP.get(sid)
        if tools:
            return sid, sorted(tools)[0]
    raise AssertionError("no runner skill registered")


def test_hint_names_the_skill_that_owns_the_tool():
    sid, tool = _runner_tool()
    hint = _not_offered_hint(tool, {"request_skill"})
    assert "request_skill" in hint and sid in hint


def test_hint_stays_generic_without_request_skill_or_owner():
    _, tool = _runner_tool()
    assert "request_skill" not in _not_offered_hint(tool, {"read_file"})
    assert "request_skill" not in _not_offered_hint("no_such_tool", {"request_skill"})


def test_refused_call_result_carries_the_hint():
    sid, tool = _runner_tool()

    async def go():
        run_block, _, _ = _make_tool_runner(
            None, set(), {}, lambda *a, **k: None, "__safe__",
            context_id="tab", offered_names=frozenset({"request_skill"}),
        )
        return await run_block(SimpleNamespace(name=tool, inputs={}, id="t1"), asyncio.Queue())

    result = asyncio.run(go())
    assert result["error"] == "tool_not_offered"
    assert sid in result["hint"]
