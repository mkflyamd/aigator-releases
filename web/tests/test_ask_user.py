"""ask_user shows a question card and ends the turn; the user's reply is the next message."""

import asyncio
import json

import app  # noqa: F401 — populates registries
import agent_loop
from llm.base import ToolCall

ASK_TOOL = {"name": "ask_user", "description": "ask", "input_schema": {"type": "object", "properties": {}}}


class _AskingProvider:
    def __init__(self, inputs):
        self.inputs = inputs
        self.calls = 0

    async def stream_turn(self, model, system, msgs, tools):
        self.calls += 1
        yield {
            "type": "done",
            "stop_reason": "tool_use",
            "text": "",
            "usage": {"input_tokens": 5, "output_tokens": 5},
            "tool_calls": [ToolCall("t1", "ask_user", self.inputs)],
            "raw_content": [{"type": "tool_use", "id": "t1", "name": "ask_user", "input": self.inputs}],
        }

    def normalize_tool_schema(self, tool):
        return tool

    def build_assistant_message(self, raw_content):
        return {"role": "assistant", "content": raw_content}

    def build_tool_result_message(self, tool_calls, results):
        return {
            "role": "user",
            "content": [
                {"type": "tool_result", "tool_use_id": tc.id, "content": json.dumps(r)}
                for tc, r in zip(tool_calls, results)
            ],
        }


def _run(provider, msgs, context_id="tab-1"):
    async def go():
        out = []
        async for chunk in agent_loop._single_agent_loop(
            provider, "claude-sonnet-5", "sys", msgs, [ASK_TOOL],
            lambda *a, **k: {}, set(), {}, lambda *a, **k: None, "safe",
            context_id=context_id,
        ):
            if chunk.startswith("data: {"):
                out.append(json.loads(chunk[6:]))
        return out

    return asyncio.run(go())


def test_question_becomes_a_card_and_the_turn_ends_without_another_model_call():
    provider = _AskingProvider({
        "question": "Which notebook should the recaps go in?",
        "options": [
            {"label": "Gator Meeting Recaps", "description": "Recommended"},
            {"label": "Work Notes"},
        ],
    })
    msgs = [{"role": "user", "content": "schedule it"}]
    events = _run(provider, msgs)

    assert provider.calls == 1
    card = next(e["ask_user"] for e in events if "ask_user" in e)
    assert card["question"] == "Which notebook should the recaps go in?"
    assert [o["label"] for o in card["options"]] == ["Gator Meeting Recaps", "Work Notes"]
    assert card["ask_id"]
    assert any(e.get("text") == card["question"] for e in events)
    assert msgs[-1]["role"] == "assistant"
    assert msgs[-1]["content"][0]["text"] == card["question"]
    assert "_await_answer" not in json.dumps(msgs)


def test_card_text_is_cleaned_and_options_are_capped():
    provider = _AskingProvider({
        "question": "Pick one‮|",
        "options": [{"label": f"opt {i}"} for i in range(9)] + [{"label": ""}, "junk"],
    })
    card = next(e["ask_user"] for e in _run(provider, [{"role": "user", "content": "x"}]) if "ask_user" in e)
    assert card["question"] == "Pick one"
    assert len(card["options"]) == agent_loop._ASK_USER_MAX_OPTIONS


def test_a_question_with_no_options_is_still_a_text_card():
    provider = _AskingProvider({"question": "What name should I use?"})
    card = next(e["ask_user"] for e in _run(provider, [{"role": "user", "content": "x"}]) if "ask_user" in e)
    assert card["options"] == []


def test_unattended_run_is_refused_with_a_hint_not_a_card():
    provider = _AskingProvider({"question": "Which notebook?"})
    provider.calls = 0
    msgs = [{"role": "user", "content": "go"}]

    async def go():
        events = []
        async for chunk in agent_loop._single_agent_loop(
            provider, "claude-sonnet-5", "sys", msgs, [ASK_TOOL],
            lambda *a, **k: {}, set(), {}, lambda *a, **k: None, "safe",
        ):
            if chunk.startswith("data: {"):
                events.append(json.loads(chunk[6:]))
            if provider.calls >= 2:
                break
        return events

    events = asyncio.run(go())
    assert not any("ask_user" in e for e in events)
    results = [b for m in msgs if m["role"] == "user" and isinstance(m["content"], list) for b in m["content"]]
    assert any("ask_user_not_allowed_unattended" in b["content"] for b in results)


def test_the_tool_ships_with_the_always_on_tools():
    from skills._always_on import tools

    assert tools.ALWAYS_ON
    assert "ask_user" in {d["name"] for d in tools.TOOL_DEFS}
    assert tools.TOOL_STATUS["ask_user"]


def test_schedule_guidance_tells_the_job_never_to_ask():
    import pathlib
    root = pathlib.Path(__file__).resolve().parent.parent / "skills"
    aigator = (root / "aigator" / "SKILL.md").read_text(encoding="utf-8")
    assert "NEEDS YOUR INPUT" in aigator and "ask_user" in aigator
