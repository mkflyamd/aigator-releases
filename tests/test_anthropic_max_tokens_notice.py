"""Issue #32: when the gateway hits stop_reason='max_tokens' mid-response while a
tool call is present, the provider silently overrides the stop_reason to
'tool_use' and recovers — the user never learns the response was truncated.

The fix factors the override decision into a pure helper that ALSO reports whether
the override masked a max_tokens truncation, so the streaming layer can surface a
user-facing notice instead of failing silently.
"""
import sys, pathlib

sys.path.insert(0, str(pathlib.Path(__file__).parent.parent / "web"))

from llm.anthropic_provider import _resolve_stop_reason


def test_max_tokens_with_tool_calls_overrides_and_flags_truncation():
    authoritative, truncated = _resolve_stop_reason("max_tokens", has_tool_calls=True)
    assert authoritative == "tool_use"
    assert truncated is True


def test_end_turn_with_tool_calls_overrides_but_is_not_truncation():
    # gateway mislabels a clean tool-use turn as end_turn — override, no truncation
    authoritative, truncated = _resolve_stop_reason("end_turn", has_tool_calls=True)
    assert authoritative == "tool_use"
    assert truncated is False


def test_clean_tool_use_is_unchanged():
    authoritative, truncated = _resolve_stop_reason("tool_use", has_tool_calls=True)
    assert authoritative == "tool_use"
    assert truncated is False


def test_max_tokens_without_tool_calls_is_not_overridden():
    authoritative, truncated = _resolve_stop_reason("max_tokens", has_tool_calls=False)
    assert authoritative == "max_tokens"
    assert truncated is False


def test_plain_end_turn_passthrough():
    authoritative, truncated = _resolve_stop_reason("end_turn", has_tool_calls=False)
    assert authoritative == "end_turn"
    assert truncated is False


def test_empty_stop_reason_defaults_to_end_turn():
    authoritative, truncated = _resolve_stop_reason("", has_tool_calls=False)
    assert authoritative == "end_turn"
    assert truncated is False
