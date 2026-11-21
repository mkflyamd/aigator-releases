"""Tool-result images must be acceptable to the Anthropic API before they are stored in history."""

import base64
import json

from llm.anthropic_provider import AnthropicProvider, _MAX_IMAGE_B64_CHARS
from llm.base import ToolCall

PNG = base64.b64encode(b"\x89PNG\r\n\x1a\n" + b"0" * 32).decode()


def _blocks(results):
    msg = AnthropicProvider().build_tool_result_message(
        [ToolCall(id="t1", name="read_web_pin", inputs={})], results
    )
    return msg["content"][0]["content"]


def _images(blocks):
    return [b for b in blocks if isinstance(b, dict) and b.get("type") == "image"]


def _notes(blocks):
    return [b["text"] for b in blocks if isinstance(b, dict) and "omitted" in b.get("text", "")]


def test_valid_png_and_jpeg_pass_through():
    blocks = _blocks([{"text": "x", "_images": [
        {"base64": PNG, "media_type": "image/png"},
        {"base64": PNG, "media_type": "image/jpeg"},
    ]}])
    assert [b["source"]["media_type"] for b in _images(blocks)] == ["image/png", "image/jpeg"]
    assert _notes(blocks) == []


def test_unsupported_media_type_is_dropped_with_a_note():
    blocks = _blocks([{"text": "x", "_images": [
        {"base64": PNG, "media_type": "image/bmp"},
        {"base64": PNG, "media_type": "image/tiff"},
        {"base64": PNG, "media_type": "image/png"},
    ]}])
    assert len(_images(blocks)) == 1
    assert _notes(blocks) == ["[2 image(s) omitted: unsupported type or too large]"]


def test_oversize_image_is_dropped_with_a_note():
    big = "A" * (_MAX_IMAGE_B64_CHARS + 4)
    blocks = _blocks([{"text": "x", "_images": [{"base64": big, "media_type": "image/png"}]}])
    assert _images(blocks) == []
    assert _notes(blocks) == ["[1 image(s) omitted: unsupported type or too large]"]
    assert big not in json.dumps(blocks)


def test_non_list_images_means_no_images():
    for bad in (None, "abc", 5):
        content = _blocks([{"text": "x", "_images": bad}])
        assert "_images" not in json.dumps(content)
        assert "x" in json.dumps(content)


def test_openai_and_truncation_tolerate_non_list_images(tmp_path, monkeypatch):
    from unittest.mock import patch
    import tool_result_truncation as trunc
    from llm.openai_provider import OpenAIProvider

    monkeypatch.setattr(trunc, "_outputs_dir", lambda: tmp_path)
    assert trunc.truncate_tool_result({"text": "x", "_images": None}, tool_name="t")["text"] == "x"
    with patch("llm.openai_provider.OpenAI"):
        p = OpenAIProvider({"id": "g", "name": "g", "type": "gateway", "base_url": "https://x.test/Unified",
                            "api_key": "aigator-fake-api-key", "models": [], "active_model": ""})
    msg = p.build_tool_result_message([ToolCall(id="c", name="t", inputs={})], [{"text": "x", "_images": None}])
    assert "image(s) omitted" not in msg["content"][0]["content"]
