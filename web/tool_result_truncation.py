"""Tool result truncation service.

When a tool result's text content exceeds MAX_TOOL_RESULT_BYTES, the full
content is written to a temp file under OUTPUTS_DIR and a compact stub is
returned in its place. This prevents large tool outputs (browser page dumps,
run_python stdout, Confluence pages, etc.) from inflating conversation history
and triggering gateway stalls on subsequent turns.

The stub includes:
- A human-readable byte count
- The absolute path to the full content on disk
- A model-facing hint telling it to use Grep/Read with offset/limit

Mirrors opencode's truncate.ts output() pattern.
"""

from __future__ import annotations

import json
import logging
import os
from secrets import token_urlsafe
from pathlib import Path
from uuid import uuid4

_log = logging.getLogger(__name__)

MAX_TOOL_RESULT_BYTES = 32 * 1024  # 32 KB — content beyond this goes to disk
_PREVIEW_BYTES = 2 * 1024          # 2 KB preview kept inline


def _outputs_dir() -> Path:
    from config import OUTPUTS_DIR
    return Path(OUTPUTS_DIR)


def _write_overflow(content: str) -> tuple[str, str, str]:
    """Write content to a private file and return (run_id, path, download_token).

    Any I/O failure (permissions, full disk, read-only FS) returns empty values so
    callers fall back to returning the original result unchanged rather than
    turning a large-but-successful tool call into a tool-call failure.
    """
    run_id = uuid4().hex[:12]
    try:
        run_dir = _outputs_dir() / run_id
        run_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
        os.chmod(run_dir, 0o700)
        out_path = run_dir / "tool_output.txt"
        fd = os.open(out_path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(content)
        os.chmod(out_path, 0o600)
        token = token_urlsafe(32)
        try:
            from routes.files import register_overflow_file

            register_overflow_file(run_id, out_path.name, token)
        except Exception as exc:
            # The private file remains useful to the local process even if the
            # optional HTTP capability registry is unavailable.
            _log.warning("[tool_truncation] failed to register download capability: %s", exc)
            token = ""
        return run_id, str(out_path), token
    except OSError as exc:
        _log.warning("[tool_truncation] failed to write overflow file: %s", exc)
        return "", "", ""


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

    try:
        original_serialized = json.dumps(result, ensure_ascii=False, default=str)
    except (TypeError, ValueError):
        # Some successful tool results can contain circular or otherwise
        # non-serializable structures. Preserve them rather than turning a
        # truncation attempt into a tool-call failure.
        return result

    _TOP_LEVEL_TEXT_KEYS = {"result", "stdout", "text", "output", "body"}

    def _should_truncate(value: object) -> bool:
        return isinstance(value, str) and len(value.encode("utf-8")) > MAX_TOOL_RESULT_BYTES

    def _stub(value: str, run_id: str, path: str, token: str) -> str:
        byte_count = len(value.encode("utf-8"))
        preview = value.encode("utf-8")[:_PREVIEW_BYTES].decode("utf-8", errors="replace")
        hint = (
            f"If read_file or grep_files are unavailable, request /file_ops first. Then use grep_files "
            f"or read_file with offset/limit to inspect specific sections."
            if not tool_name.startswith("run_python")
            else
            f"If read_file is unavailable, request /file_ops first. Then use read_file with offset/limit "
            f"to inspect specific sections of the full output."
        )
        parts = [
            f"...output truncated ({byte_count:,} bytes, {byte_count // 1024} KB)...",
            f"\nFull output saved to: {path}",
        ]
        if token:
            parts.append(f"Download URL: /api/files/{run_id}/tool_output.txt?token={token}")
        parts.append(f"\n{hint}\n")
        parts.append(f"\n--- First {_PREVIEW_BYTES} bytes ---\n{preview}")
        if len(value.encode("utf-8")) > _PREVIEW_BYTES:
            parts.append("\n... (truncated)")
        return "\n".join(parts)

    modified = dict(result)
    for key in _TOP_LEVEL_TEXT_KEYS:
        value = modified.get(key)
        if _should_truncate(value):
            run_id, path, token = _write_overflow(value)
            if path:
                modified[key] = _stub(value, run_id, path, token)
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
                    run_id, path, token = _write_overflow(text)
                    if path:
                        new_block = dict(block)
                        new_block["text"] = _stub(text, run_id, path, token)
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

    # Individual fields can all be below the per-field threshold while their
    # combined serialized result still overwhelms conversation history. Keep
    # the original complete payload on disk and expose one bounded stub.
    if len(json.dumps(modified, ensure_ascii=False, default=str).encode("utf-8")) > MAX_TOOL_RESULT_BYTES:
        run_id, path, token = _write_overflow(original_serialized)
        if path:
            return {"result": _stub(original_serialized, run_id, path, token)}

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
    run_id, path, token = _write_overflow(result)
    if not path:
        return result
    byte_count = len(result.encode("utf-8"))
    preview = result.encode("utf-8")[:_PREVIEW_BYTES].decode("utf-8", errors="replace")
    _log.info(
        "[tool_truncation] tool=%s raw string size=%d bytes -> %s",
        tool_name, byte_count, path,
    )
    download_line = (
        f"Download URL: /api/files/{run_id}/tool_output.txt?token={token}\n"
        if token else ""
    )
    return (
        f"...output truncated ({byte_count:,} bytes). "
        f"Full output saved to: {path}\n"
        f"{download_line}"
        f"If read_file or grep_files are unavailable, request /file_ops first. Then use those tools "
        f"with offset/limit.\n\n"
        f"--- First {_PREVIEW_BYTES} bytes ---\n{preview}"
        + ("\n... (truncated)" if byte_count > _PREVIEW_BYTES else "")
    )
