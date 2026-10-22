"""A result that was written to a file can be read in the same turn, without the model asking for a skill."""

import asyncio
import json
import pathlib
import sys
from types import SimpleNamespace

sys.path.insert(0, str(pathlib.Path(__file__).parent.parent / "web"))

import app  # noqa: E402,F401
import config  # noqa: E402
import tool_result_truncation as trunc  # noqa: E402
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
        turn = self._turns[len(self.tools_seen) - 1]
        yield {"type": "done", **turn}


def _call(name):
    return {"stop_reason": "tool_use", "tool_calls": [SimpleNamespace(name=name, inputs={}, id=f"id-{name}")],
            "raw_content": "x", "usage": {}}


_END = {"stop_reason": "end_turn", "tool_calls": [], "raw_content": "y", "usage": {}}


def _run(provider, execute):
    async def go():
        return [c async for c in _single_agent_loop(
            provider=provider, model="m", system="s", msgs=[{"role": "user", "content": "go"}],
            normalized_tools=[{"name": "fetch_webpage"}], execute_tool=execute, COM_BOUND_TOOLS=set(),
            TOOL_STATUS={}, _tool_toast=lambda *a, **k: None, _SLACK_SAFE_MSG="__safe__",
        )]
    return asyncio.run(go())


def test_a_spilled_result_makes_read_file_callable_this_turn(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "OUTPUTS_DIR", tmp_path)
    executed = []

    async def execute(name, inputs):
        executed.append(name)
        if name == "fetch_webpage":
            return trunc.maybe_truncate_json_result("x" * (trunc.MAX_TOOL_RESULT_BYTES + 10), tool_name=name)
        return {"content": "section"}

    provider = _Provider([_call("fetch_webpage"), _call("read_file"), _END])
    _run(provider, execute)

    assert "read_file" not in provider.tools_seen[0]
    assert {"read_file", "grep_files"} <= provider.tools_seen[1]
    assert executed == ["fetch_webpage", "read_file"]


def test_read_file_stays_unavailable_when_nothing_was_spilled():
    executed = []

    async def execute(name, inputs):
        executed.append(name)
        return {"result": "small"}

    provider = _Provider([_call("fetch_webpage"), _call("read_file"), _END])
    _run(provider, execute)

    assert not {"read_file", "grep_files"} & provider.tools_seen[1]
    assert executed == ["fetch_webpage"]


def test_the_stub_no_longer_tells_the_model_to_emit_a_skill_token(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "OUTPUTS_DIR", tmp_path)
    big = "x" * (trunc.MAX_TOOL_RESULT_BYTES + 10)
    assert "/file_ops" not in trunc.maybe_truncate_json_result(big, tool_name="fetch_webpage")
    stub = trunc.truncate_tool_result({"result": big}, tool_name="run_python")
    assert "Full output saved to" in json.dumps(stub) and "/file_ops" not in json.dumps(stub)
