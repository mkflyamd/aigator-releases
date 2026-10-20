"""A rejected tool call (missing/blank args, schema violation) gets exactly one
repair turn; the Continue banner appears only when the repair also fails."""

import asyncio
import json
import sys
import pathlib
from types import SimpleNamespace

sys.path.insert(0, str(pathlib.Path(__file__).parent.parent / "web"))

import pytest

from agent_loop import _single_agent_loop, run_three_agent_loop
from tool_repair import rejection_summaries, rejection_summary_text, stalled_chunk


def _tc(name="run_python", inputs=None, call_id="t1"):
    return SimpleNamespace(name=name, inputs={} if inputs is None else inputs, id=call_id)


def _tool_turn(*calls):
    return [{"type": "done", "stop_reason": "tool_use", "tool_calls": list(calls),
             "raw_content": [], "usage": {}}]


def _text_turn(text):
    return [{"type": "text_delta", "text": text},
            {"type": "done", "stop_reason": "end_turn", "tool_calls": [],
             "raw_content": [{"type": "text", "text": text}], "usage": {}}]


class _Provider:
    context_window = 200_000

    def __init__(self, turns):
        self._turns = turns
        self.calls = 0
        self.seen = []

    def normalize_tool_schema(self, t):
        return t

    def build_assistant_message(self, raw):
        return {"role": "assistant", "content": raw}

    def build_tool_result_message(self, tool_calls, results):
        return {"role": "user", "content": json.dumps(results)}

    async def stream_turn(self, model, system, msgs, tools):
        self.seen.append(list(msgs))
        turn = self._turns[self.calls]
        self.calls += 1
        if isinstance(turn, Exception):
            raise turn
        for event in turn:
            yield event


def _fake_tool():
    """execute_tool stand-in: run_python needs `code`; records only real executions."""
    executed = []

    async def execute_tool(name, inputs, **kw):
        if not str(inputs.get("code", "")).strip():
            return {"error": "missing_required_params", "tool": name, "missing": ["code"],
                    "required": ["code"], "hint": "Call again with every required argument: code."}
        executed.append(inputs)
        return {"stdout": "ok"}

    return execute_tool, executed


def _run_single(provider, execute_tool):
    async def go():
        return [c async for c in _single_agent_loop(
            provider=provider, model="m", system="s",
            msgs=[{"role": "user", "content": "go"}],
            normalized_tools=[{"name": "run_python", "input_schema": {"type": "object"}}],
            execute_tool=execute_tool, COM_BOUND_TOOLS=set(), TOOL_STATUS={},
            _tool_toast=lambda *a, **k: None, _SLACK_SAFE_MSG="__safe__",
        )]
    return asyncio.run(go())


def _run_three(provider, execute_tool):
    async def go():
        return [c async for c in run_three_agent_loop(
            provider, "m", "s", [{"role": "user", "content": "go"}],
            [{"name": "run_python", "input_schema": {"type": "object"}}],
            execute_tool, set(), {}, lambda *a, **k: None, "__safe__", token_budget=0,
        )]
    return asyncio.run(go())


def _events(chunks):
    return [json.loads(c[6:]) for c in chunks
            if c.startswith("data: ") and not c.startswith("data: [DONE]")]


def _stalled(chunks):
    return [e for e in _events(chunks) if e.get("stalled")]


# ── tool_repair helpers ──────────────────────────────────────────────────────

def test_rejection_summaries_name_tool_and_fields():
    calls = [_tc("run_python"), _tc("write_file", call_id="t2")]
    results = [
        {"error": "missing_required_params", "tool": "run_python", "missing": ["code"]},
        {"error": "invalid_tool_input", "tool": "write_file", "field": "path", "reason": "bad"},
    ]
    assert rejection_summaries(calls, results) == [
        {"tool": "run_python", "fields": ["code"]},
        {"tool": "write_file", "fields": ["path"]},
    ]


def test_rejection_summaries_fall_back_to_call_name_without_structure():
    assert rejection_summaries([_tc("x")], [{"error": "json decode failure"}]) == [
        {"tool": "x", "fields": []},
    ]


def test_stalled_chunk_names_tool_fields_and_carries_retry_note():
    chunk = stalled_chunk([{"tool": "run_python", "fields": ["code"]}])
    assert chunk.startswith('data: {"stalled"')  # routes/chat.py holds stalled chunks by this prefix
    evt = json.loads(chunk[6:])
    assert evt["stalled"] is True
    assert "run_python" in evt["message"] and "code" in evt["message"]
    assert "run_python" in evt["retry_note"] and "code" in evt["retry_note"]
    assert evt["failed_calls"] == [{"tool": "run_python", "fields": ["code"]}]


def test_rejection_summary_text():
    assert rejection_summary_text(
        {"error": "missing_required_params", "tool": "run_python", "missing": ["code"]}
    ) == "Rejected run_python: missing code"
    assert rejection_summary_text(
        {"error": "invalid_tool_input", "tool": "write_file", "field": "path"}
    ) == "Rejected write_file: invalid path"
    assert rejection_summary_text({"error": "boom"}) is None
    assert rejection_summary_text("text") is None


# ── real execute_tool: a rejected call never runs the tool ───────────────────

async def test_rejected_call_never_executes_and_reports_required_fields(monkeypatch):
    import shared
    from app import execute_tool

    ran = []

    def probe(code: str):
        ran.append(code)
        return {"stdout": code}

    monkeypatch.setitem(shared.TOOL_DISPATCH, "repair_probe", probe)
    for inputs in ({}, {"code": ""}, {"code": "   "}):
        result = await execute_tool("repair_probe", inputs)
        assert result["error"] == "missing_required_params"
        assert result["tool"] == "repair_probe"
        assert result["missing"] == ["code"]
        assert result["required"] == ["code"]
        assert "code" in result["hint"]
    assert ran == []


# ── single-agent loop ────────────────────────────────────────────────────────

def test_missing_field_gets_exactly_one_repair_call_and_task_resumes():
    execute, executed = _fake_tool()
    provider = _Provider([
        _tool_turn(_tc(inputs={})),
        _tool_turn(_tc(inputs={"code": "print(1)"})),
        _text_turn("The script ran and printed 1, so the task is complete."),
    ])
    chunks = _run_single(provider, execute)
    assert provider.calls == 3
    assert executed == [{"code": "print(1)"}]
    assert not _stalled(chunks)
    # the repair call saw the structured rejection
    repair_ctx = provider.seen[1][-1]["content"]
    assert '"missing": ["code"]' in repair_ctx and '"tool": "run_python"' in repair_ctx
    assert chunks[-1] == "data: [DONE]\n\n"


def test_repair_that_fails_again_stalls_naming_tool_and_fields():
    execute, executed = _fake_tool()
    provider = _Provider([
        _tool_turn(_tc(inputs={})),
        _tool_turn(_tc(inputs={})),
        _text_turn("unexpected third call"),
    ])
    chunks = _run_single(provider, execute)
    assert provider.calls == 2
    assert executed == []
    stalled = _stalled(chunks)
    assert len(stalled) == 1
    assert "run_python" in stalled[0]["message"] and "code" in stalled[0]["message"]
    assert stalled[0]["failed_calls"] == [{"tool": "run_python", "fields": ["code"]}]
    assert not any("could not form valid tool calls" in c for c in chunks)
    assert chunks[-1] == "data: [DONE]\n\n"


def test_successful_repair_resets_the_repair_budget():
    execute, executed = _fake_tool()
    provider = _Provider([
        _tool_turn(_tc(inputs={})),
        _tool_turn(_tc(inputs={"code": "1"})),
        _tool_turn(_tc(inputs={})),
        _tool_turn(_tc(inputs={"code": "2"})),
        _text_turn("Both scripts ran successfully and the task is complete."),
    ])
    chunks = _run_single(provider, execute)
    assert provider.calls == 5
    assert executed == [{"code": "1"}, {"code": "2"}]
    assert not _stalled(chunks)


def test_schema_violation_counts_as_a_rejected_call():
    async def execute(name, inputs, **kw):
        return {"error": "invalid_tool_input", "tool": name, "field": "code",
                "reason": "123 is not of type 'string'", "hint": "Fix 'code'."}

    provider = _Provider([
        _tool_turn(_tc(inputs={"code": 123})),
        _tool_turn(_tc(inputs={"code": 456})),
        _text_turn("unexpected third call"),
    ])
    chunks = _run_single(provider, execute)
    assert provider.calls == 2
    assert _stalled(chunks)[0]["failed_calls"] == [{"tool": "run_python", "fields": ["code"]}]
