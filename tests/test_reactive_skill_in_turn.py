"""A tool result that flags a skill (an image marker) makes that skill's tools callable in the same turn,
without re-running the turn, and never grants a runner."""

import asyncio
import json
import pathlib
import sys
from types import SimpleNamespace

sys.path.insert(0, str(pathlib.Path(__file__).parent.parent / "web"))

import app  # noqa: E402,F401
import pytest  # noqa: E402
import shared  # noqa: E402
from agent_loop import _single_agent_loop  # noqa: E402


class _Provider:
    context_window = 200_000

    def __init__(self, turns):
        self._turns = turns
        self.tools_seen = []

    def normalize_tool_schema(self, t):
        return t

    def build_assistant_message(self, raw):
        return {"role": "assistant", "content": raw}

    def build_tool_result_message(self, tool_calls, results):
        return {"role": "tool", "content": json.dumps(results)}

    async def stream_turn(self, model, system, msgs, tools):
        self.tools_seen.append({t["name"] for t in tools})
        yield {"type": "done", **self._turns[len(self.tools_seen) - 1]}


def _call(name):
    return {"stop_reason": "tool_use", "tool_calls": [SimpleNamespace(name=name, inputs={}, id=f"id-{name}")],
            "raw_content": "x", "usage": {}}


_END = {"stop_reason": "end_turn", "tool_calls": [], "raw_content": "y", "usage": {}}


def _def(name):
    return {"name": name, "description": "t", "input_schema": {"type": "object", "properties": {}}}


@pytest.fixture(autouse=True)
def skills(monkeypatch):
    monkeypatch.setitem(shared.SKILL_TOOLS_MAP, "img_skill", {"img_tool"})
    monkeypatch.setitem(shared.SKILL_TOOLS_MAP, "code_runner", {"run_python"})
    monkeypatch.setattr(shared, "SKILL_ACTIVATES_ON_MAP", {"img_skill": ["[image:"], "code_runner": ["[image:"]})
    monkeypatch.setattr(shared, "TOOLS", [*shared.TOOLS, _def("img_tool"), _def("run_python")])


def _run(provider):
    executed, chunks = [], []

    async def execute(name, inputs):
        executed.append(name)
        return {"result": "a chat with [image: photo.png]"}

    async def go():
        async for c in _single_agent_loop(
            provider=provider, model="m", system="s", msgs=[{"role": "user", "content": "go"}],
            normalized_tools=[_def("read_chat")], execute_tool=execute, COM_BOUND_TOOLS=set(),
            TOOL_STATUS={}, _tool_toast=lambda *a, **k: None, _SLACK_SAFE_MSG="__safe__", context_id="ctx",
        ):
            chunks.append(c)

    asyncio.run(go())
    return executed, chunks


def test_the_flagged_skill_is_callable_in_the_same_turn_and_nothing_is_replayed():
    provider = _Provider([_call("read_chat"), _call("img_tool"), _END])
    executed, chunks = _run(provider)
    assert "img_tool" not in provider.tools_seen[0] and "img_tool" in provider.tools_seen[1]
    assert executed == ["read_chat", "img_tool"]
    assert not any("reactive_skills" in c for c in chunks)


def test_a_tool_result_can_never_grant_a_runner():
    provider = _Provider([_call("read_chat"), _call("run_python"), _END])
    executed, _ = _run(provider)
    assert "run_python" not in provider.tools_seen[1]
    assert executed == ["read_chat"]
