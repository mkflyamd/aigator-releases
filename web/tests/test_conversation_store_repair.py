"""Regression tests for conversation history repair (multi-tab / window-slice corruption).

Both failures produced the same gateway 400 — "unexpected `tool_use_id` found in
`tool_result` blocks ... must have a corresponding `tool_use` block in the previous
message":
  * get_window sliced the sliding window mid tool-pair, orphaning a tool_result at
    the front when the matching tool_use fell into the summarized half.
  * two concurrent requests on the same context_id (two browser tabs sharing
    localStorage's active-tab id) interleaved their tool_use/tool_result turns into
    one shared history.

`_repair_tool_pairs` keeps a pair only when an assistant message is immediately
followed by a user message carrying the matching result; everything else is dropped.
"""
from conversation_store import _repair_tool_pairs as R
from conversation_store import _repair_openai_tool_pairs as RO


def test_clean_pair_is_untouched():
    clean = [
        {"role": "user", "content": "hi"},
        {"role": "assistant", "content": [
            {"type": "text", "text": "t"},
            {"type": "tool_use", "id": "A", "name": "x", "input": {}},
        ]},
        {"role": "user", "content": [{"type": "tool_result", "tool_use_id": "A", "content": "r"}]},
    ]
    assert R(clean) == clean


def test_window_slice_orphan_is_dropped():
    # Leading tool_result whose tool_use fell into the summarized half.
    orphan = [
        {"role": "user", "content": "summary"},
        {"role": "user", "content": [{"type": "tool_result", "tool_use_id": "Z", "content": "r"}]},
        {"role": "assistant", "content": "ok"},
    ]
    assert R(orphan) == [
        {"role": "user", "content": "summary"},
        {"role": "assistant", "content": "ok"},
    ]


def test_interleaved_turns_drop_all_tool_blocks_keep_text():
    inter = [
        {"role": "assistant", "content": [{"type": "tool_use", "id": "A", "name": "x", "input": {}}]},
        {"role": "assistant", "content": [
            {"type": "text", "text": "keepme"},
            {"type": "tool_use", "id": "B", "name": "y", "input": {}},
        ]},
        {"role": "user", "content": [{"type": "tool_result", "tool_use_id": "A", "content": "r"}]},
        {"role": "user", "content": [{"type": "tool_result", "tool_use_id": "B", "content": "r"}]},
    ]
    assert R(inter) == [{"role": "assistant", "content": [{"type": "text", "text": "keepme"}]}]


def test_trailing_unpaired_tool_use_is_dropped():
    trail = [
        {"role": "user", "content": "hi"},
        {"role": "assistant", "content": [{"type": "tool_use", "id": "A", "name": "x", "input": {}}]},
    ]
    assert R(trail) == [{"role": "user", "content": "hi"}]


def test_empty_input_returns_empty():
    assert R([]) == []


# ── OpenAI-wire-format repair (enterprise gateway 400 root cause) ──────────────

def test_openai_clean_pair_is_untouched():
    clean = [
        {"role": "user", "content": "hi"},
        {"role": "assistant", "content": None, "tool_calls": [
            {"id": "A", "type": "function", "function": {"name": "x", "arguments": "{}"}},
        ]},
        {"role": "tool", "tool_call_id": "A", "content": "result"},
        {"role": "assistant", "content": "done"},
    ]
    assert RO(clean) == clean


def test_openai_orphaned_leading_tool_message_is_dropped():
    orphan = [
        {"role": "user", "content": "summary"},
        {"role": "tool", "tool_call_id": "Z", "content": "result"},
        {"role": "assistant", "content": "ok"},
    ]
    assert RO(orphan) == [
        {"role": "user", "content": "summary"},
        {"role": "assistant", "content": "ok"},
    ]


def test_openai_unanswered_assistant_tool_calls_dropped():
    trail = [
        {"role": "user", "content": "hi"},
        {"role": "assistant", "content": None, "tool_calls": [
            {"id": "A", "type": "function", "function": {"name": "x", "arguments": "{}"}},
        ]},
    ]
    assert RO(trail) == [{"role": "user", "content": "hi"}]


def test_openai_unanswered_tool_calls_but_keep_text():
    trail = [
        {"role": "assistant", "content": "here is my plan", "tool_calls": [
            {"id": "A", "type": "function", "function": {"name": "x", "arguments": "{}"}},
        ]},
    ]
    assert RO(trail) == [{"role": "assistant", "content": "here is my plan"}]


def test_openai_partial_tool_calls_keeps_answered_only():
    msgs = [
        {"role": "assistant", "content": None, "tool_calls": [
            {"id": "A", "type": "function", "function": {"name": "x", "arguments": "{}"}},
            {"id": "B", "type": "function", "function": {"name": "y", "arguments": "{}"}},
        ]},
        {"role": "tool", "tool_call_id": "A", "content": "result A"},
    ]
    assert RO(msgs) == [
        {"role": "assistant", "content": None, "tool_calls": [
            {"id": "A", "type": "function", "function": {"name": "x", "arguments": "{}"}},
        ]},
        {"role": "tool", "tool_call_id": "A", "content": "result A"},
    ]


def test_openai_repair_ignores_anthropic_messages():
    anthropic = [
        {"role": "assistant", "content": [
            {"type": "tool_use", "id": "A", "name": "x", "input": {}},
        ]},
        {"role": "user", "content": [{"type": "tool_result", "tool_use_id": "A", "content": "r"}]},
    ]
    assert RO(anthropic) == anthropic


def test_openai_empty_input_returns_empty():
    assert RO([]) == []
