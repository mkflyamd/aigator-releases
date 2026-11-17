"""An image attached on turn one can still be found on a later turn: the base64 is stripped from
history, but the saved file path stays as text."""

import asyncio
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "web"))

import app  # noqa: E402,F401
from conversation_store import ConversationStore  # noqa: E402
from routes.chat import _with_image_path_note  # noqa: E402

SAVED = r"C:\Users\someone\Pictures\AIGator\uploads\20261105-101500_slide.png"
IMAGE = {"type": "image", "source": {"type": "base64", "media_type": "image/png", "data": "AAAA"}}


def _first_turn():
    return [IMAGE, {"type": "text", "text": "draft an update from this slide"}]


def test_the_saved_path_is_added_next_to_the_image():
    out = _with_image_path_note(_first_turn(), [SAVED], ["slide.png"])
    assert out[:2] == _first_turn()
    note = out[2]["text"]
    assert SAVED in note and "slide.png" in note and "describe_images" in note


def test_plain_text_and_messages_without_paths_are_untouched():
    assert _with_image_path_note("hello", [SAVED], ["slide.png"]) == "hello"
    assert _with_image_path_note(_first_turn(), None, None) == _first_turn()
    assert _with_image_path_note(_first_turn(), [], []) == _first_turn()


def test_the_path_is_still_in_the_history_after_the_image_is_stripped():
    store = ConversationStore()
    turn_one = {"role": "user", "content": _with_image_path_note(_first_turn(), [SAVED], ["slide.png"])}
    reply = {"role": "assistant", "content": [{"type": "text", "text": "Here is the draft."}]}
    asyncio.run(store.append("ctx", [turn_one, reply]))
    asyncio.run(store.append("ctx", [{"role": "user", "content": "bisect?"}, reply]))
    window = asyncio.run(store.get_window("ctx", "any-model"))
    blocks = [b for m in window if isinstance(m["content"], list) for b in m["content"]]
    assert not any(b.get("type") == "image" for b in blocks)
    assert any(SAVED in b.get("text", "") for b in blocks)


def test_an_image_with_no_saved_path_says_to_ask_for_it_again():
    store = ConversationStore()
    asyncio.run(store.append("ctx", [{"role": "user", "content": [IMAGE]}, {"role": "assistant", "content": "ok"}]))
    window = asyncio.run(store.get_window("ctx", "any-model"))
    assert "re-send" in str(window)
