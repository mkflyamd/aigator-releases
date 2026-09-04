"""Tool result truncation service.

When a tool result's text content exceeds MAX_TOOL_RESULT_BYTES, the full
content is written to a temp file under OUTPUTS_DIR and a compact stub is
returned in its place. This prevents large tool outputs (browser page dumps,
run_python stdout, Confluence pages, etc.) from inflating conversation history
and triggering gateway stalls on subsequent turns.

The stub includes:
- A human-readable byte count
- The absolute path to the full content on disk
- A download URL via /api/files/<run_id>/<filename>
- A model-facing hint telling it to use Grep/Read with offset/limit

Mirrors opencode's truncate.ts output() pattern.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from uuid import uuid4

_log = logging.getLogger(__name__)

MAX_TOOL_RESULT_BYTES = 32 * 1024  # 32 KB — content beyond this goes to disk
_PREVIEW_BYTES = 2 * 1024          # 2 KB preview kept inline


def _outputs_dir() -> Path:
    from config import OUTPUTS_DIR
    return Path(OUTPUTS_DIR)


def _write_overflow(content: str) -> tuple[str, str]:
    """Write content to a unique file under OUTPUTS_DIR. Returns (run_id, path).

    Any I/O failure (permissions, full disk, read-only FS) returns ("", "") so
    callers fall back to returning the original result unchanged rather than
    turning a large-but-successful tool call into a tool-call failure.
    """
    run_id = uuid4().hex[:12]
    try:
        run_dir = _outputs_dir() / run_id
        run_dir.mkdir(parents=True, exist_ok=True)
        out_path = run_dir / "tool_output.txt"
        out_path.write_text(content, encoding="utf-8")
        return run_id, str(out_path)
    except OSError as exc:
        _log.warning("[tool_truncation] failed to write overflow file: %s", exc)
        return "", ""


def truncate_tool_result(result: object, *, tool_name: str = "") -> object:
    """Cap large text content in a tool result dict.

    Walks the result for string values that exceed MAX_TOOL_RESULT_BYTES.
    Qualifying values are replaced with a compact stub pointing at the
    full content on disk. Non-dict results are returned unchanged.

    Only top-level string fields and the common nested shapes used by our
    tools are inspected (result, stdout, content, text, output). Deep
    recursive traversal is deliberately avoided — we don't want to silently
    truncate structured data like JSON arrays or tool metadata.
    """
    if not isinstance(result, dict):
        return result

    _TOP_LEVEL_TEXT_KEYS = {"result", "stdout", "text", "output", "body"}

    def _should_truncate(value: object) -> bool:
        return isinstance(value, str) and len(value.encode("utf-8")) > MAX_TOOL_RESULT_BYTES

    def _stub(value: str, run_id: str, path: str) -> str:
        byte_count = len(value.encode("utf-8"))
        preview = value.encode("utf-8")[:_PREVIEW_BYTES].decode("utf-8", errors="replace")
        download_url = f"/api/files/{run_id}/tool_output.txt" if run_id else ""
        hint = (
            f"Use Grep to search the full content or Read with offset/limit to view specific sections."
            if not tool_name.startswith("run_python")
            else
            f"Use Read with offset/limit to view specific sections of the full output."
        )
        parts = [
            f"...output truncated ({byte_count:,} bytes, {byte_count // 1024} KB)...",
            f"\nFull output saved to: {path}",
        ]
        if download_url:
            parts.append(f"Download URL: {download_url}")
        parts.append(f"\n{hint}\n")
        parts.append(f"\n--- First {_PREVIEW_BYTES} bytes ---\n{preview}")
        if len(value.encode("utf-8")) > _PREVIEW_BYTES:
            parts.append("\n... (truncated)")
        return "\n".join(parts)

    modified = dict(result)
    for key in _TOP_LEVEL_TEXT_KEYS:
        value = modified.get(key)
        if _should_truncate(value):
            run_id, path = _write_overflow(value)
            if path:
                modified[key] = _stub(value, run_id, path)
                _log.info(
                    "[tool_truncation] tool=%s key=%s size=%d bytes -> %s",
                    tool_name, key, len(value.encode("utf-8")), path,
                )

    # Also handle Anthropic-style content arrays: [{"type": "text", "text": "..."}]
    content = modified.get("content")
    if isinstance(content, list):
        new_content = []
        changed = False
        for block in content:
            if isinstance(block, dict) and block.get("type") == "text":
                text = block.get("text", "")
                if _should_truncate(text):
                    run_id, path = _write_overflow(text)
                    if path:
                        new_block = dict(block)
                        new_block["text"] = _stub(text, run_id, path)
                        new_content.append(new_block)
                        changed = True
                        _log.info(
                            "[tool_truncation] tool=%s content[text] size=%d bytes -> %s",
                            tool_name, len(text.encode("utf-8")), path,
                        )
                        continue
            new_content.append(block)
        if changed:
            modified["content"] = new_content

    return modified


def maybe_truncate_json_result(result: object, *, tool_name: str = "") -> object:
    """Truncate a result that is a large raw JSON string (not a dict).

    Some tools return a JSON-serialized string as their top-level result.
    If the raw string is over the limit, write it to disk and return a stub dict.
    """
    if not isinstance(result, str):
        return result
    if len(result.encode("utf-8")) <= MAX_TOOL_RESULT_BYTES:
        return result
    run_id, path = _write_overflow(result)
    if not path:
        return result
    byte_count = len(result.encode("utf-8"))
    preview = result.encode("utf-8")[:_PREVIEW_BYTES].decode("utf-8", errors="replace")
    _log.info(
        "[tool_truncation] tool=%s raw string size=%d bytes -> %s",
        tool_name, byte_count, path,
    )
    return (
        f"...output truncated ({byte_count:,} bytes). "
        f"Full output saved to: {path}\n"
        f"Use Grep or Read with offset/limit.\n\n"
        f"--- First {_PREVIEW_BYTES} bytes ---\n{preview}"
        + ("\n... (truncated)" if byte_count > _PREVIEW_BYTES else "")
    )
