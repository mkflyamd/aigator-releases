"""Regression: a stored `thinking` block's `signature` is cryptographically tied to
the model that generated it. Replaying it back to a different model after a
mid-conversation model switch caused 400 errors ('thinking.signature: Field
required') from the API. `get_window()` must permanently downgrade stored
`thinking` blocks to plain `text` the first turn after a model switch, and leave
them untouched when the model hasn't changed.
"""
import asyncio
import sys
import pathlib

sys.path.insert(0, str(pathlib.Path(__file__).parent.parent / "web"))

from conversation_store import ConversationStore


def _thinking_turn(text="reasoning about the answer", signature="sig-abc"):
    return {
        "role": "assistant",
        "content": [
            {"type": "thinking", "thinking": text, "signature": signature},
            {"type": "text", "text": "final answer"},
        ],
    }


def _thinking_types(window):
    assistant_msg = next(m for m in window if m["role"] == "assistant")
    return [b["type"] for b in assistant_msg["content"]], assistant_msg


def test_same_model_keeps_thinking_block_intact():
    async def _go():
        store = ConversationStore()
        await store.append("ctx1", [{"role": "user", "content": "hi"}, _thinking_turn()])
        await store.get_window("ctx1", model="claude-sonnet-4-6")
        return await store.get_window("ctx1", model="claude-sonnet-4-6")

    window = asyncio.run(_go())
    types, assistant_msg = _thinking_types(window)
    assert "thinking" in types
    thinking_block = next(b for b in assistant_msg["content"] if b["type"] == "thinking")
    assert thinking_block["signature"] == "sig-abc"


def test_model_switch_downgrades_thinking_to_text():
    async def _go():
        store = ConversationStore()
        await store.append("ctx2", [{"role": "user", "content": "hi"}, _thinking_turn()])
        await store.get_window("ctx2", model="claude-sonnet-4-6")
        return await store.get_window("ctx2", model="claude-sonnet-5")

    window = asyncio.run(_go())
    types, assistant_msg = _thinking_types(window)
    assert "thinking" not in types
    assert any(b["type"] == "text" and b["text"] == "reasoning about the answer" for b in assistant_msg["content"])


def test_downgrade_is_permanent_across_subsequent_windows():
    async def _go():
        store = ConversationStore()
        await store.append("ctx3", [{"role": "user", "content": "hi"}, _thinking_turn()])
        await store.get_window("ctx3", model="claude-sonnet-4-6")
        await store.get_window("ctx3", model="claude-sonnet-5")
        # Switch back to the original model — the block was already flattened, so it
        # stays plain text rather than being "restored" (documented tradeoff).
        return await store.get_window("ctx3", model="claude-sonnet-4-6")

    window = asyncio.run(_go())
    types, _ = _thinking_types(window)
    assert "thinking" not in types


def test_no_model_arg_never_downgrades():
    async def _go():
        store = ConversationStore()
        await store.append("ctx4", [{"role": "user", "content": "hi"}, _thinking_turn()])
        return await store.get_window("ctx4")

    window = asyncio.run(_go())
    types, _ = _thinking_types(window)
    assert "thinking" in types


def test_empty_thinking_text_downgrades_to_placeholder():
    async def _go():
        store = ConversationStore()
        turn = {
            "role": "assistant",
            "content": [{"type": "thinking", "thinking": "", "signature": "sig-x"}],
        }
        await store.append("ctx5", [{"role": "user", "content": "hi"}, turn])
        await store.get_window("ctx5", model="model-a")
        return await store.get_window("ctx5", model="model-b")

    window = asyncio.run(_go())
    assistant_msg = next(m for m in window if m["role"] == "assistant")
    assert assistant_msg["content"] == [{"type": "text", "text": "[reasoning omitted]"}]


def test_delete_clears_last_model_tracking():
    async def _go():
        store = ConversationStore()
        await store.append("ctx6", [_thinking_turn()])
        await store.get_window("ctx6", model="model-a")
        await store.delete("ctx6")
        await store.append("ctx6", [_thinking_turn()])
        # No prior model recorded for this context anymore, so no downgrade should
        # occur even though "model-b" differs from what was used before the delete.
        return await store.get_window("ctx6", model="model-b")

    window = asyncio.run(_go())
    types, _ = _thinking_types(window)
    assert "thinking" in types
