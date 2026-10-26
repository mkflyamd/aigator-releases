"""Compaction must never drop the current turn.

A user attaching an image (or sending any message) while the stored history is
large used to trigger compaction that rebuilt the request from the store alone,
discarding the in-flight user message and ending the request on an assistant
message (a 400 on models without assistant prefill).
"""

import asyncio
import json
import sys
import pathlib

sys.path.insert(0, str(pathlib.Path(__file__).parent.parent / "web"))

import agent_loop
import shared
from agent_loop import _single_agent_loop
from conversation_store import ConversationStore

SUMMARIZER_SYSTEM = "You are a helpful assistant."


class _Provider:
    def normalize_tool_schema(self, t):
        return t

    def build_assistant_message(self, raw):
        return {"role": "assistant", "content": raw}

    def build_tool_result_message(self, tool_calls, results):
        return {"role": "tool", "content": json.dumps(results)}

    def __init__(self):
        self.main_requests = []
        self.summarizer_calls = 0

    async def stream_turn(self, model, system, msgs, tools):
        if system == SUMMARIZER_SYSTEM:
            self.summarizer_calls += 1
            yield {"type": "text_delta", "text": "SUMMARY OF EARLIER TURNS"}
            yield {"type": "done", "stop_reason": "end_turn", "tool_calls": [], "raw_content": "", "usage": {}}
            return
        self.main_requests.append([dict(m) for m in msgs])
        yield {"type": "text_delta", "text": "ANSWER"}
        yield {"type": "done", "stop_reason": "end_turn", "tool_calls": [], "raw_content": "ANSWER", "usage": {}}


def _history(n=10, size=400):
    return [
        {"role": "user" if i % 2 == 0 else "assistant", "content": f"{i}:" + "x" * size}
        for i in range(n)
    ]


def _run(history, new_user_content, window, monkeypatch):
    provider = _Provider()
    store = ConversationStore()
    monkeypatch.setattr(shared, "conversation_store", store)
    monkeypatch.setattr(agent_loop, "_model_context_window", lambda model: window)

    async def go():
        await store.append("ctx", history)
        window_msgs = await store.get_window("ctx", "m")
        msgs = window_msgs + [{"role": "user", "content": new_user_content}]
        chunks = []
        async for c in _single_agent_loop(
            provider=provider, model="m", system="s", msgs=msgs, normalized_tools=[],
            execute_tool=None, COM_BOUND_TOOLS=set(), TOOL_STATUS={},
            _tool_toast=lambda *a, **k: None, _SLACK_SAFE_MSG="__safe__",
            context_id="ctx",
        ):
            chunks.append(c)
        return msgs, chunks

    msgs, chunks = asyncio.run(go())
    return provider, msgs, chunks


def _compacted(chunks):
    return any("Compacting conversation history" in c for c in chunks)


def _image_block(chars):
    return {"type": "image", "source": {"type": "base64", "media_type": "image/jpeg", "data": "A" * chars}}


# ── Pins current behaviour that must survive the fix ─────────────────────────


def test_text_heavy_history_still_triggers_proactive_compaction(monkeypatch):
    provider, _, chunks = _run(_history(), "next question", 1000, monkeypatch)
    assert _compacted(chunks)
    assert provider.summarizer_calls == 1


def test_small_history_does_not_compact(monkeypatch):
    provider, _, chunks = _run(_history(n=4, size=10), "next question", 200_000, monkeypatch)
    assert not _compacted(chunks)
    assert provider.summarizer_calls == 0


def test_compact_with_fewer_than_eight_messages_is_a_noop():
    async def go():
        store = ConversationStore()
        await store.append("c", _history(n=6, size=5))
        return await store.compact("c", _Provider(), "m")

    msgs, meta = asyncio.run(go())
    assert meta is None
    assert len(msgs) == 6


# ── Reproduce the defects ────────────────────────────────────────────────────


def test_attached_image_does_not_trigger_compaction(monkeypatch):
    content = [{"type": "text", "text": "what is this?"}, _image_block(2_000_000)]
    provider, _, chunks = _run(_history(n=10, size=5), content, 200_000, monkeypatch)
    assert not _compacted(chunks)
    assert provider.summarizer_calls == 0
    assert provider.main_requests[0][-1]["content"] == content


def test_current_user_message_survives_compaction(monkeypatch):
    content = [{"type": "text", "text": "what is this?"}, _image_block(100)]
    provider, _, chunks = _run(_history(), content, 1000, monkeypatch)
    assert _compacted(chunks)
    sent = provider.main_requests[0]
    assert sent[-1]["role"] == "user"
    assert sent[-1]["content"] == content


def test_request_never_ends_on_an_assistant_message_after_compaction(monkeypatch):
    provider, _, _ = _run(_history(), "next question", 1000, monkeypatch)
    assert provider.main_requests[0][-1]["role"] == "user"


def test_nothing_to_compact_leaves_the_request_untouched(monkeypatch):
    big = "y" * 20_000
    provider, _, _ = _run(_history(n=4, size=5), big, 1000, monkeypatch)
    sent = provider.main_requests[0]
    assert sent[-1] == {"role": "user", "content": big}
    assert len(sent) == 5


def test_in_flight_tool_messages_survive_a_post_call_compaction(monkeypatch):
    class _ToolProvider(_Provider):
        async def stream_turn(self, model, system, msgs, tools):
            if system == SUMMARIZER_SYSTEM:
                async for e in super().stream_turn(model, system, msgs, tools):
                    yield e
                return
            self.main_requests.append([dict(m) for m in msgs])
            if len(self.main_requests) == 1:
                yield {"type": "done", "stop_reason": "tool_use", "tool_calls": [_Call()],
                       "raw_content": "CALL", "usage": {"input_tokens": 900}}
            else:
                yield {"type": "text_delta", "text": "ANSWER"}
                yield {"type": "done", "stop_reason": "end_turn", "tool_calls": [],
                       "raw_content": "ANSWER", "usage": {}}

    class _Call:
        name = "t"
        inputs = {}
        id = "t1"

    provider = _ToolProvider()
    store = ConversationStore()
    monkeypatch.setattr(shared, "conversation_store", store)
    monkeypatch.setattr(agent_loop, "_model_context_window", lambda model: 1000)

    async def execute(name, inputs):
        return {"ok": True}

    async def go():
        await store.append("ctx", _history(n=10, size=5))
        msgs = await store.get_window("ctx", "m") + [{"role": "user", "content": "do it"}]
        async for _ in _single_agent_loop(
            provider=provider, model="m", system="s", msgs=msgs, normalized_tools=[{"name": "t"}],
            execute_tool=execute, COM_BOUND_TOOLS=set(), TOOL_STATUS={},
            _tool_toast=lambda *a, **k: None, _SLACK_SAFE_MSG="__safe__", context_id="ctx",
        ):
            pass
        return msgs

    msgs = asyncio.run(go())
    second = provider.main_requests[1]
    assert any(m.get("content") == "do it" for m in second)
    assert any(m.get("content") == "CALL" for m in second)
    assert msgs[-1] == {"role": "assistant", "content": "ANSWER"}


def test_text_blocks_next_to_an_image_still_count_toward_the_estimate():
    text = "x" * 40_000
    mixed = [{"role": "user", "content": [{"type": "text", "text": text}, _image_block(10)]}]
    assert agent_loop._estimate_tokens(mixed) >= 10_000
    nested = [{"role": "user", "content": [{
        "type": "tool_result", "tool_use_id": "t1",
        "content": [{"type": "text", "text": text}, _image_block(10)],
    }]}]
    assert agent_loop._estimate_tokens(nested) >= 10_000


def test_large_text_beside_an_image_triggers_proactive_compaction(monkeypatch):
    content = [{"type": "text", "text": "x" * 60_000}, _image_block(100)]
    provider, _, chunks = _run(_history(n=10, size=5), content, 20_000, monkeypatch)
    assert _compacted(chunks)
    sent = provider.main_requests[0]
    assert sent[-1]["role"] == "user"
    assert sent[-1]["content"] == content


def test_three_agent_post_call_compaction_keeps_the_current_turn(monkeypatch):
    class _ThreeAgentProvider(_Provider):
        def __init__(self):
            super().__init__()
            self.verifier_requests = []

        async def stream_turn(self, model, system, msgs, tools):
            if system == SUMMARIZER_SYSTEM:
                async for e in super().stream_turn(model, system, msgs, tools):
                    yield e
                return
            if system.endswith(agent_loop._PLANNER_SUFFIX):
                yield {"type": "text_delta", "text": "PLAN"}
                yield {"type": "done", "stop_reason": "end_turn", "tool_calls": [], "raw_content": "PLAN", "usage": {}}
            elif system.endswith(agent_loop._EXECUTOR_SUFFIX):
                yield {"type": "text_delta", "text": "DRAFT"}
                yield {"type": "done", "stop_reason": "end_turn", "tool_calls": [], "raw_content": "DRAFT",
                       "usage": {"input_tokens": 990}}
            else:
                self.verifier_requests.append([dict(m) for m in msgs])
                yield {"type": "text_delta", "text": "FINAL"}
                yield {"type": "done", "stop_reason": "end_turn", "tool_calls": [], "raw_content": "FINAL", "usage": {}}

    provider = _ThreeAgentProvider()
    store = ConversationStore()
    monkeypatch.setattr(shared, "conversation_store", store)
    monkeypatch.setattr(agent_loop, "_model_context_window", lambda model: 1000)

    async def go():
        await store.append("ctx", _history(n=10, size=5))
        msgs = await store.get_window("ctx", "m") + [{"role": "user", "content": "do the thing"}]
        chunks = []
        async for c in agent_loop.run_three_agent_loop(
            provider=provider, model="m", system="s", msgs=msgs, normalized_tools=[],
            execute_tool=None, COM_BOUND_TOOLS=set(), TOOL_STATUS={},
            _tool_toast=lambda *a, **k: None, _SLACK_SAFE_MSG="__safe__", context_id="ctx",
        ):
            chunks.append(c)
        return msgs, chunks

    msgs, chunks = asyncio.run(go())
    assert _compacted(chunks)
    assert "SUMMARY OF EARLIER TURNS" in msgs[0]["content"]
    assert msgs[-1] == {"role": "user", "content": "do the thing"}
    assert "Original: do the thing" in provider.verifier_requests[0][0]["content"]


def test_turn_after_compaction_stays_in_the_callers_message_list(monkeypatch):
    _, msgs, chunks = _run(_history(), "next question", 1000, monkeypatch)
    assert _compacted(chunks)
    assert msgs[-1] == {"role": "assistant", "content": "ANSWER"}
    assert any(m.get("content") == "next question" for m in msgs)


# ── The chat route persists the turn after an in-place compaction ────────────


def test_chat_route_persists_the_whole_turn_after_compaction(monkeypatch):
    import app  # noqa: F401 — importing populates the skill registries at startup
    import conversation_store as cs
    from routes import chat as chat_module

    async def fake_summary(turns, provider, model):
        return "SUMMARY"

    async def fake_loop(**kwargs):
        msgs = kwargs["msgs"]
        meta = await agent_loop._compact_in_place(
            msgs, kwargs["turn_user_msg"], kwargs["context_id"], kwargs["provider"], kwargs["model"]
        )
        assert meta
        msgs.append({"role": "assistant", "content": "ANSWER"})
        yield f"data: {json.dumps({'text': 'ok'})}\n\n"

    store = ConversationStore()
    monkeypatch.setattr(shared, "conversation_store", store)
    monkeypatch.setattr(cs, "_llm_summarize", fake_summary)
    monkeypatch.setattr(agent_loop, "_single_agent_loop", fake_loop)
    monkeypatch.setattr(chat_module, "_classify_skills_via_llm", lambda *a, **k: [])
    monkeypatch.setattr(chat_module, "_load_config", lambda: {"three_agent_mode": False})

    async def run():
        await store.append("persist-ctx", _history(n=10, size=5))
        resp = await chat_module.chat(chat_module.ChatRequest(message="hello", context_id="persist-ctx"))
        await shared.chat_task_store._store[json.loads(resp.body)["task_id"]]["asyncio_task"]
        return store._store["persist-ctx"]

    stored = asyncio.run(run())
    assert stored[0] == {"role": "user", "content": "SUMMARY"}
    assert stored[-2:] == [
        {"role": "user", "content": "hello"},
        {"role": "assistant", "content": "ANSWER"},
    ]
    assert len(stored) == 1 + 6 + 2
