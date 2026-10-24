"""A background run that hits its step limit must say so in its result, not finish with an empty one."""

import asyncio
import json
import types

import app  # noqa: F401 — populates registries
import agent_loop
import task_queue as tq


def _run_coro(coro):
    return asyncio.new_event_loop().run_until_complete(coro)


def _chunk(payload):
    return f"data: {json.dumps(payload)}\n\n"


def test_step_limit_is_recorded_as_the_task_result(tmp_path, monkeypatch):
    monkeypatch.setattr(tq, "DB_PATH", tmp_path / "tasks.db")
    _run_coro(tq.init_db())

    async def run_fn(prompt, skills=None):
        yield _chunk({"token": "narration"})
        yield _chunk({"phase": "tool_round"})
        yield _chunk({"exhausted": True, "iterations": 80, "message": "ignored"})
        yield _chunk({"usage": {"input_tokens": 7, "output_tokens": 3}})
        yield "data: [DONE]\n\n"

    async def go():
        task_id = await tq.enqueue("weekly sync")
        await tq._run_task(task_id, "weekly sync", run_fn)
        return await tq.get_task(task_id)

    task = _run_coro(go())
    assert "80-step limit" in task["result"]
    assert task["input_tokens"] == 7 and task["output_tokens"] == 3


class _OneToolCallProvider:
    async def stream_turn(self, model, system, msgs, tools):
        call = types.SimpleNamespace(id="c1", name="read_calendar", inputs={"n": len(msgs)})
        yield {
            "type": "done",
            "stop_reason": "tool_use",
            "text": "",
            "usage": {"input_tokens": 5, "output_tokens": 5},
            "tool_calls": [call],
            "raw_content": [],
        }

    def build_assistant_message(self, raw_content):
        return {"role": "assistant", "content": raw_content}

    def build_tool_result_message(self, tool_calls, results):
        return {"role": "user", "content": "results"}


def test_loop_reports_usage_and_its_own_limit_when_exhausted(monkeypatch):
    monkeypatch.setattr(agent_loop, "MAX_ITERATIONS", 2)
    async def go():
        out = []
        async for chunk in agent_loop._single_agent_loop(
            _OneToolCallProvider(), "claude-sonnet-5", "sys", [{"role": "user", "content": "hi"}], [],
            lambda *a, **k: {}, set(), {}, lambda *a, **k: None, "safe",
        ):
            if chunk.startswith("data: {"):
                out.append(json.loads(chunk[6:]))
        return out

    events = _run_coro(go())
    assert [e["iterations"] for e in events if e.get("exhausted")] == [2]
    assert events[-1]["usage"]["input_tokens"] == 10
