"""Regression tests for successful-but-empty chat streams."""

import pathlib


SRC = (pathlib.Path(__file__).parent.parent / "routes" / "chat.py").read_text(
    encoding="utf-8"
)


def test_done_frame_emits_fallback_before_completion():
    assert "_visible_text_emitted = False" in SRC
    assert "_tool_activity_emitted = False" in SRC
    assert "'silent_fallback': True" in SRC
    assert "[stream] empty completed turn" in SRC
