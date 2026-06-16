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
