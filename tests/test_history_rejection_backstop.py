"""A provider 400 that says the conversation history itself is malformed
(trailing thinking block, empty content) gets exactly one repair attempt with
all thinking blocks stripped from history; if that also fails the user sees a
structured `stalled` event, never raw provider JSON, and the error is never
treated as a transient retry or a failover trigger."""

import asyncio
import json
import sys
import pathlib
from types import SimpleNamespace

sys.path.insert(0, str(pathlib.Path(__file__).parent.parent / "web"))

from agent_loop import _single_agent_loop, run_three_agent_loop
from tool_repair import is_history_rejection


class _Http400(Exception):
    status_code = 400


_RAW = (
    "Error code: 400 - {'type': 'error', 'error': {'type': 'invalid_request_error', "
    "'message': 'messages.3.content.1: The final block in an assistant message cannot be thinking.'}}"
)

_HISTORY_WITH_THINKING = [
    {"role": "user", "content": "first"},
    {
        "role": "assistant",
        "content": [
            {"type": "thinking", "thinking": "plan", "signature": "sig"},
            {"type": "text", "text": "done"},
        ],
    },
    {"role": "user", "content": "go"},
]


def _text_turn(text):
    return [
        {"type": "text_delta", "text": text},
        {
            "type": "done",
            "stop_reason": "end_turn",
            "tool_calls": [],
            "raw_content": [{"type": "text", "text": text}],
            "usage": {},
        },
    ]


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
        self.seen.append(json.loads(json.dumps(msgs)))
        turn = self._turns[min(self.calls, len(self._turns) - 1)]
        self.calls += 1
        if isinstance(turn, Exception):
            raise turn
        for event in turn:
            yield event


async def _execute_tool(name, inputs, **kw):
    return {"stdout": "ok"}


def _run_single(provider):
    async def go():
        return [
            c
            async for c in _single_agent_loop(
                provider=provider,
                model="m",
                system="s",
                msgs=json.loads(json.dumps(_HISTORY_WITH_THINKING)),
                normalized_tools=[{"name": "run_python", "input_schema": {"type": "object"}}],
                execute_tool=_execute_tool,
                COM_BOUND_TOOLS=set(),
                TOOL_STATUS={},
                _tool_toast=lambda *a, **k: None,
                _SLACK_SAFE_MSG="__safe__",
            )
        ]

    return asyncio.run(go())


def _run_three(provider):
    async def go():
        return [
            c
            async for c in run_three_agent_loop(
                provider,
                "m",
                "s",
                json.loads(json.dumps(_HISTORY_WITH_THINKING)),
                [{"name": "run_python", "input_schema": {"type": "object"}}],
                _execute_tool,
                set(),
                {},
                lambda *a, **k: None,
                "__safe__",
                token_budget=0,
            )
        ]

    return asyncio.run(go())


def _events(chunks):
    return [
        json.loads(c[6:])
        for c in chunks
        if c.startswith("data: ") and not c.startswith("data: [DONE]")
    ]


def _stalled(chunks):
    return [e for e in _events(chunks) if e.get("stalled")]


def _has_thinking(msgs):
    return any(
        isinstance(m.get("content"), list)
        and any(b.get("type") in ("thinking", "redacted_thinking") for b in m["content"])
        for m in msgs
    )


def test_matches_history_shape_400s_only():
    assert is_history_rejection(_Http400(_RAW))
    assert is_history_rejection(_Http400("messages.2: text content blocks must be non-empty"))
    assert not is_history_rejection(ValueError(_RAW))  # not a 400
    assert not is_history_rejection(_Http400("tools.3.custom.input_schema: invalid"))
    assert not is_history_rejection(TimeoutError("stream timed out"))


def test_single_loop_strips_thinking_and_retries_once():
    provider = _Provider([_Http400(_RAW), _text_turn("recovered")])
    chunks = _run_single(provider)
    assert provider.calls == 2
    assert _has_thinking(provider.seen[0])
    assert not _has_thinking(provider.seen[1])
    assert not _stalled(chunks)
    assert any("recovered" in c for c in chunks)


def test_single_loop_second_rejection_stalls_without_raw_json():
    provider = _Provider([_Http400(_RAW)])
    chunks = _run_single(provider)
    assert provider.calls == 2
    stalled = _stalled(chunks)
    assert len(stalled) == 1
    assert stalled[0]["retry_note"]
    joined = "".join(chunks)
    assert "invalid_request_error" not in joined
    assert "Error code: 400" not in joined
    assert chunks[-1] == "data: [DONE]\n\n"


def test_executor_loop_strips_thinking_and_retries_once():
    provider = _Provider(
        [
            _text_turn("1. Do the thing."),
            _Http400(_RAW),
            _text_turn("The task is complete and everything worked."),
            _text_turn("The task is complete and everything worked."),
        ]
    )
    chunks = _run_three(provider)
    assert not _stalled(chunks)
    assert not _has_thinking(provider.seen[2])


def test_executor_loop_second_rejection_stalls_without_raw_json():
    provider = _Provider([_text_turn("1. Do the thing."), _Http400(_RAW)])
    chunks = _run_three(provider)
    assert provider.calls == 3  # planner + original + one repair
    stalled = _stalled(chunks)
    assert len(stalled) == 1
    joined = "".join(chunks)
    assert "invalid_request_error" not in joined
    assert chunks[-1] == "data: [DONE]\n\n"
