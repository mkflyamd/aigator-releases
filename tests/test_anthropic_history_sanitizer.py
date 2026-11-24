"""Regression: the API rejects an assistant message whose final block is
thinking ("The final block in an assistant message cannot be thinking") and
rejects empty assistant content. Stalled/cancelled/max_tokens turns can leave
that shape in history, so the provider sanitizes every request before sending.
"""

import sys
import pathlib

sys.path.insert(0, str(pathlib.Path(__file__).parent.parent / "web"))

from llm.anthropic_provider import _sanitize_history_for_send


def _thinking(text="hmm"):
    return {"type": "thinking", "thinking": text, "signature": "sig"}


def test_trailing_thinking_after_text_is_stripped():
    msgs = [{"role": "assistant", "content": [{"type": "text", "text": "hi"}, _thinking()]}]
    out = _sanitize_history_for_send(msgs)
    assert out[0]["content"] == [{"type": "text", "text": "hi"}]


def test_thinking_followed_by_empty_text_is_stripped():
    msgs = [{"role": "assistant", "content": [_thinking(), {"type": "text", "text": ""}]}]
    out = _sanitize_history_for_send(msgs)
    blocks = out[0]["content"]
    assert blocks and all(b["type"] == "text" and b["text"].strip() for b in blocks)


def test_thinking_only_message_gets_text_placeholder():
    msgs = [{"role": "assistant", "content": [_thinking()]}]
    out = _sanitize_history_for_send(msgs)
    assert out[0]["role"] == "assistant"
    assert len(out[0]["content"]) == 1
    assert out[0]["content"][0]["type"] == "text"
    assert out[0]["content"][0]["text"].strip()


def test_redacted_thinking_trailing_is_stripped():
    msgs = [
        {
            "role": "assistant",
            "content": [{"type": "text", "text": "a"}, {"type": "redacted_thinking", "data": "x"}],
        }
    ]
    out = _sanitize_history_for_send(msgs)
    assert out[0]["content"] == [{"type": "text", "text": "a"}]


def test_thinking_before_tool_use_is_kept():
    content = [_thinking(), {"type": "tool_use", "id": "t1", "name": "n", "input": {}}]
    msgs = [{"role": "assistant", "content": content}]
    out = _sanitize_history_for_send(msgs)
    assert out[0]["content"] == content


def test_user_messages_and_string_content_untouched():
    msgs = [
        {"role": "user", "content": "hello"},
        {"role": "assistant", "content": "plain"},
        {"role": "user", "content": [{"type": "tool_result", "tool_use_id": "t1", "content": "x"}]},
    ]
    assert _sanitize_history_for_send(msgs) == msgs


def test_input_is_not_mutated():
    original = [{"role": "assistant", "content": [{"type": "text", "text": "hi"}, _thinking()]}]
    snapshot = [{"role": "assistant", "content": list(original[0]["content"])}]
    _sanitize_history_for_send(original)
    assert original == snapshot
