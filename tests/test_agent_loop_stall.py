"""#4: a turn that ends right after a tool fails must surface a 'stalled' signal
so the UI can offer Continue — instead of dying silently after a timeout/error.
"""
import asyncio
import json
import sys
import pathlib
from types import SimpleNamespace

sys.path.insert(0, str(pathlib.Path(__file__).parent.parent / "web"))

import agent_loop
from agent_loop import _failed_tool_results, _single_agent_loop


def test_failed_tool_results_detects_error_dicts():
    assert _failed_tool_results([{"error": "boom"}]) == ["boom"]
    assert _failed_tool_results([{"error": "a"}, {"error": "b"}]) == ["a", "b"]


def test_failed_tool_results_ignores_success_and_non_dicts():
    assert _failed_tool_results([{"stdout": "ok"}, {"ok": True}]) == []
    assert _failed_tool_results([False, None, "text"]) == []
    # empty/falsey error value is not a failure
    assert _failed_tool_results([{"error": ""}]) == []


# ── End-to-end: a tool fails, then the model stops → expect a stalled chunk ──

class _FakeProvider:
    context_window = 200_000

    def normalize_tool_schema(self, t):
        return t

    def build_assistant_message(self, raw):
        return {"role": "assistant", "content": raw}

    def build_tool_result_message(self, tool_calls, results):
        return {"role": "tool", "content": json.dumps(results)}

    def __init__(self, turns):
        self._turns = turns
        self._i = 0

    async def stream_turn(self, model, system, msgs, tools):
        turn = self._turns[self._i]
        self._i += 1
        for piece in turn.get("text_pieces", []):
            yield {"type": "text_delta", "text": piece}
        yield {"type": "done", **turn["done"]}


def _collect(gen):
    async def run():
        out = []
        async for chunk in gen:
            out.append(chunk)
        return out
    return asyncio.get_event_loop().run_until_complete(run())


def _make_tc(name="run_python"):
    return SimpleNamespace(name=name, inputs={}, id="t1")


def test_stalled_signal_emitted_when_turn_ends_after_tool_failure():
    # Turn 1: model calls a tool. Turn 2: tool failed, model stops with text.
    provider = _FakeProvider([
        {"done": {"stop_reason": "tool_use", "tool_calls": [_make_tc()],
                  "raw_content": "x", "usage": {}}},
        {"text_pieces": ["Let me write it to a file and run it."],
         "done": {"stop_reason": "end_turn", "tool_calls": [],
                  "raw_content": "y", "usage": {}}},
    ])

    async def fake_execute(name, inputs):
        return {"error": "Code execution timed out after 60s."}

    chunks = _collect(_single_agent_loop(
        provider=provider, model="m", system="s", msgs=[{"role": "user", "content": "go"}],
        normalized_tools=[], execute_tool=fake_execute,
        COM_BOUND_TOOLS=set(), TOOL_STATUS={}, _tool_toast=lambda *a, **k: None,
        _SLACK_SAFE_MSG="__safe__",
    ))

    stalled = [json.loads(c[6:]) for c in chunks
               if c.startswith("data: ") and not c.startswith("data: [DONE]")
               and '"stalled"' in c]
    assert len(stalled) == 1, f"expected one stalled chunk, got {chunks}"
    assert "timed out" in stalled[0]["message"]
    assert chunks[-1] == "data: [DONE]\n\n"


def test_no_stalled_signal_on_clean_finish():
    # Turn 1: tool succeeds. Turn 2: model stops normally → no stalled signal.
    provider = _FakeProvider([
        {"done": {"stop_reason": "tool_use", "tool_calls": [_make_tc()],
                  "raw_content": "x", "usage": {}}},
        {"text_pieces": ["All done."],
         "done": {"stop_reason": "end_turn", "tool_calls": [],
                  "raw_content": "y", "usage": {}}},
    ])

    async def fake_execute(name, inputs):
        return {"stdout": "ok", "error": None}

    chunks = _collect(_single_agent_loop(
        provider=provider, model="m", system="s", msgs=[{"role": "user", "content": "go"}],
        normalized_tools=[], execute_tool=fake_execute,
        COM_BOUND_TOOLS=set(), TOOL_STATUS={}, _tool_toast=lambda *a, **k: None,
        _SLACK_SAFE_MSG="__safe__",
    ))

    assert not any('"stalled"' in c for c in chunks), f"unexpected stalled chunk in {chunks}"
    assert chunks[-1] == "data: [DONE]\n\n"
