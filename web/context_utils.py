"""Adaptive tool result compression.

Only activates when accumulated tool result size in a single turn exceeds
COMPRESSION_THRESHOLD_CHARS (40,000). Below threshold: verbatim. Above: compressed.
COM-bound tools (Word/Excel/PPT) are never compressed.
All truncations include an explicit marker so the model knows its view is partial.
"""
from __future__ import annotations
import json
import re

COMPRESSION_THRESHOLD_CHARS = 40_000

COM_BOUND_TOOLS = {
    "update_docx", "read_docx", "get_docx_info",
    "update_excel", "read_excel", "get_excel_info",
    "update_pptx", "read_pptx", "get_pptx_info",
}

TOOL_RESULT_LIMITS: dict[str, dict] = {
    "read_email": {"max_items": 20, "max_body_chars": 1500, "items_key": "emails", "body_key": "body"},
    "search_email": {"max_items": 20, "max_body_chars": 1500, "items_key": "emails", "body_key": "body"},
    "read_teams_chats": {"max_items": None, "max_body_chars": 600, "items_key": "messages", "body_key": "content"},
    "read_channel_messages": {"max_items": 30, "max_body_chars": 400, "items_key": "messages", "body_key": "content"},
    "read_onedrive_file": {
        "max_chars": 30_000,
        "truncation_note": (
            "[TRUNCATED: document exceeds 30,000 chars. Only the first portion is visible. "
            "Ask the user which section to focus on before proceeding.]"
        ),
    },
    "fetch_webpage": {"max_chars": 6_000, "truncation_note": "[...page truncated at 6,000 chars]"},
    "_default": {"max_chars": 4_000, "truncation_note": "[...result truncated]"},
}


def compress_tool_result(tool_name: str, result: dict | str, total_chars_so_far: int) -> dict | str:
    """Compress result if accumulated turn size warrants it.

    Returns original result unchanged if:
    - Tool is COM-bound (user is actively editing Word/Excel/PPT)
    - Total accumulated chars are below threshold (40K)
    """
    if tool_name in COM_BOUND_TOOLS:
        return result
    result_str = result if isinstance(result, str) else json.dumps(result)
    if total_chars_so_far + len(result_str) < COMPRESSION_THRESHOLD_CHARS:
        return result
    limits = TOOL_RESULT_LIMITS.get(tool_name, TOOL_RESULT_LIMITS["_default"])
    if isinstance(result, dict):
        return _compress_dict_result(result, limits)
    return _compress_str_result(result, limits)


def _compress_dict_result(result: dict, limits: dict) -> dict:
    compressed = dict(result)

    # List-of-items tools (email, teams, channel messages)
    items_key = limits.get("items_key")
    if items_key and items_key in result:
        items = list(result[items_key])
        max_items = limits.get("max_items")
        if max_items and len(items) > max_items:
            omitted = len(items) - max_items
            items = items[:max_items]
            compressed[f"_{items_key}_omitted"] = (
                f"[{omitted} items omitted. Use search tools to find specific items.]"
            )
        body_key = limits.get("body_key", "body")
        max_body = limits.get("max_body_chars")
        if max_body:
            for i, item in enumerate(items):
                item = dict(item)
                body = item.get(body_key, "")
                if isinstance(body, str):
                    # Strip HTML tags before truncating
                    body = re.sub(r"<[^>]+>", " ", body)
                    body = re.sub(r"\s+", " ", body).strip()
                    if len(body) > max_body:
                        body = body[:max_body] + "... [body truncated]"
                    item[body_key] = body
                items[i] = item
        compressed[items_key] = items

    # Single large text field (onedrive file, webpage)
    max_chars = limits.get("max_chars")
    if max_chars:
        for key in ("content", "text", "body"):
            val = compressed.get(key, "")
            if isinstance(val, str) and len(val) > max_chars:
                note = limits.get("truncation_note", "[...truncated]")
                compressed[key] = val[:max_chars] + "\n\n" + note
                break

    return compressed


def _compress_str_result(result: str, limits: dict) -> str:
    max_chars = limits.get("max_chars", 4_000)
    if len(result) > max_chars:
        return result[:max_chars] + "\n\n" + limits.get("truncation_note", "[...truncated]")
    return result
