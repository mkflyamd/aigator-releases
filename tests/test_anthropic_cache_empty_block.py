"""Regression: the Vertex/Anthropic API rejects cache_control on empty text
blocks ('cache_control cannot be set for empty text blocks'). Abnormal/stalled
turns can leave an empty trailing text block; the cache breakpoint must skip it.
"""
import sys
import pathlib

sys.path.insert(0, str(pathlib.Path(__file__).parent.parent / "web"))

from llm.anthropic_provider import _is_empty_text_block, _cacheable_block_index


def test_empty_text_block_detected():
    assert _is_empty_text_block({"type": "text", "text": ""})
    assert _is_empty_text_block({"type": "text", "text": "   "})
    assert _is_empty_text_block({"type": "text"})  # missing text key


def test_non_empty_and_non_text_blocks_are_cacheable():
    assert not _is_empty_text_block({"type": "text", "text": "hi"})
    assert not _is_empty_text_block({"type": "tool_use", "id": "t1", "input": {}})
    assert not _is_empty_text_block({"type": "tool_result", "content": "x"})


def test_cacheable_index_skips_trailing_empty_text():
    content = [
        {"type": "text", "text": "real answer"},
        {"type": "text", "text": ""},
    ]
    assert _cacheable_block_index(content) == 0


def test_cacheable_index_picks_last_when_non_empty():
    content = [
        {"type": "text", "text": "a"},
        {"type": "tool_use", "id": "t1", "input": {}},
    ]
    assert _cacheable_block_index(content) == 1


def test_cacheable_index_none_when_all_empty():
    content = [{"type": "text", "text": ""}, {"type": "text", "text": "  "}]
    assert _cacheable_block_index(content) is None


def test_cacheable_index_tool_result_after_empty_text():
    # A tool_use turn may carry an empty text block followed by nothing, but a
    # tool_result message has a real block — that one must be chosen.
    content = [{"type": "tool_result", "tool_use_id": "t1", "content": "data"}]
    assert _cacheable_block_index(content) == 0
