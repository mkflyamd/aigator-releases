"""Drives the real /api/chat handler: a bare follow-up in a chat that already ran a Slack
tool must be offered the Slack tools. Only the LLM classifier and the agent loop are
stubbed; skill selection, tool filtering and the server-side conversation store are real.
"""

import asyncio
import json

import app  # noqa: F401 — importing populates the skill registries at startup
import shared
from routes import chat as chat_module

SLACK_TOOL = "slack_search_public_and_private"


def _tool_name(tool):
    return tool.get("name") or tool.get("function", {}).get("name")


def _offered_to_loop(monkeypatch, context_id, message, seeded):
    import agent_loop

    captured = {}

    async def fake_loop(**kwargs):
        captured["tools"] = {_tool_name(t) for t in kwargs["normalized_tools"]}
        yield f"data: {json.dumps({'text': 'ok'})}\n\n"

    monkeypatch.setattr(agent_loop, "_single_agent_loop", fake_loop)
    monkeypatch.setattr(chat_module, "_classify_skills_via_llm", lambda *a, **k: [])
    monkeypatch.setattr(chat_module, "_load_config", lambda: {"three_agent_mode": False})

    async def run():
        if seeded:
            await shared.conversation_store.append(context_id, seeded)
        resp = await chat_module.chat(chat_module.ChatRequest(message=message, context_id=context_id))
        task_id = json.loads(resp.body)["task_id"]
        await shared.chat_task_store._store[task_id]["asyncio_task"]

    asyncio.run(run())
    return captured["tools"]


def _slack_turn():
    return [
        {"role": "user", "content": "catch me up on ext-amd-fireworks"},
        {"role": "assistant", "content": [{"type": "tool_use", "id": "t1", "name": SLACK_TOOL, "input": {"query": "x"}}]},
        {"role": "user", "content": [{"type": "tool_result", "tool_use_id": "t1", "content": "[]"}]},
        {"role": "assistant", "content": "Nothing found."},
    ]


def test_a_bare_follow_up_is_offered_the_slack_tools_the_chat_already_used(monkeypatch):
    offered = _offered_to_loop(monkeypatch, "cf-int-used-slack", "now try fireworks", _slack_turn())
    assert SLACK_TOOL in offered


def test_a_fresh_chat_is_not_offered_slack_for_the_same_follow_up(monkeypatch):
    offered = _offered_to_loop(monkeypatch, "cf-int-fresh", "now try fireworks", None)
    assert SLACK_TOOL not in offered


def test_a_refused_call_does_not_widen_the_tool_set(monkeypatch):
    refused = _slack_turn()
    refused[2]["content"][0]["content"] = '{"error": "tool_not_offered"}'
    offered = _offered_to_loop(monkeypatch, "cf-int-refused", "now try fireworks", refused)
    assert SLACK_TOOL not in offered
