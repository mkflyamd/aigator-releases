"""Waiting for the user's allow/deny answer is not the model going silent.

A source card can wait 300 s for an answer while the stream's inter-chunk idle budget is
180 s. The watchdog used to trip during the wait and kill the turn as soon as the user
answered (or banner it as "went silent" when the card expired).
"""

import asyncio
import json

import app  # noqa: F401 — importing populates the skill registries at startup
import shared
from routes import chat as chat_module
from agent_loop import awaiting_human, is_awaiting_human


def _run_turn(monkeypatch, context_id, wait_for_user):
    import agent_loop

    async def fake_loop(**kwargs):
        yield f"data: {json.dumps({'tool_call_start': {'id': 'c1', 'name': 'x'}})}\n\n"
        if wait_for_user:
            with awaiting_human(context_id):
                await asyncio.sleep(1.0)
        else:
            await asyncio.sleep(1.0)
        yield f"data: {json.dumps({'text': 'after the answer'})}\n\n"

    monkeypatch.setattr(agent_loop, "_single_agent_loop", fake_loop)
    monkeypatch.setattr(chat_module, "_classify_skills_via_llm", lambda *a, **k: [])
    monkeypatch.setattr(chat_module, "_load_config", lambda: {"three_agent_mode": False})
    monkeypatch.setattr(chat_module, "_FIRST_TOKEN_TIMEOUT_S", 0.3)
    monkeypatch.setattr(chat_module, "_INTER_CHUNK_TIMEOUT_S", 0.3)
    monkeypatch.setattr(chat_module, "_WATCHDOG_POLL_S", 0.05)

    async def run():
        resp = await chat_module.chat(chat_module.ChatRequest(message="hello", context_id=context_id))
        task_id = json.loads(resp.body)["task_id"]
        await shared.chat_task_store._store[task_id]["asyncio_task"]
        return "".join(shared.chat_task_store._store[task_id]["chunks"])

    return asyncio.run(run())


def test_a_wait_on_the_user_longer_than_the_idle_budget_does_not_stall_the_turn(monkeypatch):
    out = _run_turn(monkeypatch, "wd-human", wait_for_user=True)
    assert '"stalled"' not in out
    assert "after the answer" in out


def test_the_same_silence_without_a_human_wait_still_stalls(monkeypatch):
    out = _run_turn(monkeypatch, "wd-silent", wait_for_user=False)
    assert '"stalled"' in out


def test_the_marker_is_scoped_and_nests():
    assert not is_awaiting_human("wd-scope")
    with awaiting_human("wd-scope"):
        with awaiting_human("wd-scope"):
            assert is_awaiting_human("wd-scope")
        assert is_awaiting_human("wd-scope")
        assert not is_awaiting_human("other")
    assert not is_awaiting_human("wd-scope")


def test_the_marker_clears_when_the_wait_raises():
    try:
        with awaiting_human("wd-raise"):
            raise RuntimeError("boom")
    except RuntimeError:
        pass
    assert not is_awaiting_human("wd-raise")
