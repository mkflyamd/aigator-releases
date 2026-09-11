"""Server-side conversation history store.

Keyed by context_id (tab ID). Maintains a 20-turn sliding window.
Tool results are never summarized to protect structured data (dates, IDs,
email addresses). Only user/assistant text is compressed when overflow occurs.
"""

from __future__ import annotations
import asyncio

MAX_TURNS = 20

# Assistant messages larger than this are stored as stubs in history. The full
# Threshold for the large-code-block check in _semantic_stub. HTML docs and
# fenced widgets are always stubbed regardless of size; large code blocks are
# stubbed only when they exceed this threshold (avoids stubbing short snippets).
MAX_ASSISTANT_MSG_BYTES = 8 * 1024


class ConversationStore:
    def __init__(self) -> None:
        self._store: dict[str, list[dict]] = {}
        self._last_model: dict[str, str] = {}
        self._lock = asyncio.Lock()
        self._ctx_locks: dict[str, asyncio.Lock] = {}

    def lock_for(self, context_id: str) -> asyncio.Lock:
        """Per-context turn lock. Hold it for a whole agent turn so two concurrent
        requests on the same context_id (e.g. two browser tabs sharing localStorage)
        run sequentially instead of interleaving tool_use/tool_result blocks into a
        single shared history."""
        lock = self._ctx_locks.get(context_id)
        if lock is None:
            lock = asyncio.Lock()
            self._ctx_locks[context_id] = lock
        return lock

    async def append(self, context_id: str, messages: list[dict]) -> None:
        async with self._lock:
            if context_id not in self._store:
                self._store[context_id] = []
            self._store[context_id].extend(
                _repair_openai_tool_pairs(_drop_orphaned_tool_use(messages))
            )

    async def get_window(self, context_id: str, model: str | None = None) -> list[dict]:
        """Return active message window. Prepends a text summary if history > MAX_TURNS*2.

        The window is always repaired (orphaned tool_use/tool_result blocks removed)
        before returning, so a window that was sliced mid tool-pair — or a history that
        got interleaved by concurrent same-context requests — never produces a
        `tool_result` without its matching `tool_use` when sent to the model.

        If `model` differs from the model used on the previous turn for this context,
        stored `thinking` blocks are permanently downgraded to plain `text` first — a
        thinking block's `signature` is cryptographically tied to the model that
        produced it and isn't guaranteed to validate when replayed to a different model.
        """
        async with self._lock:
            if model and self._last_model.get(context_id) not in (None, model):
                self._store[context_id] = _downgrade_thinking_blocks(
                    self._store.get(context_id, [])
                )
            if model:
                self._last_model[context_id] = model
            msgs = self._store.get(context_id, [])
            if not msgs:
                return []
            cutoff = MAX_TURNS * 2
            if len(msgs) <= cutoff:
                return _truncate_large_assistant_messages(
                    _strip_image_blocks(_repair_all(list(msgs)))
                )
            old = msgs[:-cutoff]
            recent = msgs[-cutoff:]
            summary = _summarize_old_turns(old)
            return [{"role": "user", "content": summary}] + _truncate_large_assistant_messages(
                _strip_image_blocks(_repair_all(recent))
            )

    async def seed(self, context_id: str, history: list[dict]) -> None:
        """Seed from browser-sent history (backward compat, first message only)."""
        async with self._lock:
            if context_id not in self._store:
                self._store[context_id] = list(history)

    async def delete(self, context_id: str) -> None:
        async with self._lock:
            self._store.pop(context_id, None)
            self._last_model.pop(context_id, None)

    async def compact(
        self, context_id: str, provider, model: str
    ) -> tuple[list[dict], dict | None]:
        """LLM-summarize old turns to reduce context size.

        Keeps the last 6 messages verbatim (3 user/assistant pairs).
        Replaces everything older with a single synthetic summary message.
        Returns (new message window, compaction meta) — meta is None when there
        was nothing to compact. Meta carries `turn_count` and `summary_text` so
        callers can surface a seam marker to the user instead of rewriting
        history silently.
        """
        async with self._lock:
            msgs = self._store.get(context_id, [])
            if len(msgs) < 8:
                return list(msgs), None
            keep_n = 6
            old_turns = msgs[:-keep_n]
            recent = _repair_all(msgs[-keep_n:])

        summary_text = await _llm_summarize(old_turns, provider, model)
        summary_msg = {"role": "user", "content": summary_text}

        async with self._lock:
            self._store[context_id] = [summary_msg] + recent
        meta = {"turn_count": len(old_turns), "summary_text": summary_text}
        return [summary_msg] + _truncate_large_assistant_messages(
            _strip_image_blocks(recent)
        ), meta

    def has(self, context_id: str) -> bool:
        return context_id in self._store


_HTML_DOC_RE = __import__("re").compile(
    r"(```(?:html:widget|html:live|html)\n[\s\S]*?```|<!DOCTYPE\s+html[\s\S]*?</html>)",
    __import__("re").IGNORECASE,
)
_LARGE_CODE_RE = __import__("re").compile(r"```[\w:]*\n(?:(?!```)[\s\S]){2000,}```")


def _semantic_stub(content: str) -> str | None:
    """Return a compact semantic stub if content contains a large HTML doc or code block.

    The stub tells the model what was rendered without re-sending the payload.
    Returns None if the content doesn't match any known large-artifact pattern.

    Design mirrors opencode's compaction approach: tool results are replaced with
    "[Old tool result content cleared]"; here assistant HTML/code artifacts are
    replaced with a description of what was produced. The model already generated
    the content and the user already saw it — it doesn't need to be re-sent.
    """
    stripped = content.strip()

    # Bare HTML document (no fence — model dropped the fence on a follow-up turn)
    if __import__("re").match(r"<!DOCTYPE\s+html", stripped, __import__("re").IGNORECASE):
        line_count = content.count("\n")
        return (
            f"[HTML document rendered to user — {len(stripped):,} chars, ~{line_count} lines. "
            f"The document was displayed as a widget. Do not reproduce it verbatim; "
            f"refer to it as 'the widget I just generated' if the user asks about it.]"
        )

    # Fenced HTML widget
    if _HTML_DOC_RE.search(content):
        line_count = content.count("\n")
        return (
            f"[HTML widget rendered to user — {len(stripped):,} chars, ~{line_count} lines. "
            f"The document was displayed as an interactive widget. Do not reproduce it verbatim.]"
        )

    # Large code block (>2KB inside a single fence, AND total > 8KB)
    if _LARGE_CODE_RE.search(content) and len(stripped.encode("utf-8")) > MAX_ASSISTANT_MSG_BYTES:
        return (
            f"[Large code/output rendered to user — {len(stripped):,} chars. "
            f"Refer to it as 'the code I just wrote' rather than reproducing it verbatim.]"
        )

    # Fallback: any large plain-text response (web scrapes, verbose analysis, etc.)
    # not caught by the above patterns. Preserves the P0-3 regression fix: large
    # browser dumps and stdout blobs that contain no HTML or code fences still get
    # stubbed rather than inflating context on every subsequent turn.
    encoded = stripped.encode("utf-8")
    if len(encoded) > MAX_ASSISTANT_MSG_BYTES:
        line_count = content.count("\n")
        return (
            f"[Large response rendered to user — {len(encoded):,} bytes, ~{line_count} lines. "
            f"Refer to it rather than reproducing it verbatim.]"
        )

    return None


def _truncate_large_assistant_messages(messages: list[dict]) -> list[dict]:
    """Replace large HTML artifacts and code blocks in assistant history with semantic stubs.

    Rather than blindly stubbing any message over a byte threshold, this function
    specifically identifies:
    - Bare HTML documents (model dropped the ```html fence)
    - Fenced HTML widgets (```html / ```html:widget / ```html:live)
    - Large code blocks (>2KB of code content)

    These are replaced with a short description of what was produced. Small responses,
    markdown prose, and structured data are preserved verbatim.

    This mirrors opencode's compaction.ts pattern: tool results are replaced with
    content-cleared stubs in history, never verbatim. The model doesn't need the
    full 3,500-token HTML to understand "I already generated an ELI5 widget".
    """
    result = []
    for msg in messages:
        if msg.get("role") != "assistant":
            result.append(msg)
            continue
        content = msg.get("content")
        if isinstance(content, str):
            stub = _semantic_stub(content)
            if stub:
                result.append({**msg, "content": stub})
                continue
        elif isinstance(content, list):
            new_blocks = []
            changed = False
            for block in content:
                if (
                    isinstance(block, dict)
                    and block.get("type") == "text"
                    and isinstance(block.get("text"), str)
                ):
                    stub = _semantic_stub(block["text"])
                    if stub:
                        new_blocks.append({**block, "text": stub})
                        changed = True
                        continue
                new_blocks.append(block)
            if changed:
                result.append({**msg, "content": new_blocks})
                continue
        result.append(msg)
    return result


def _strip_image_blocks(messages: list[dict]) -> list[dict]:
    """Remove image/document content blocks from historical messages.

    Images are only valid in the turn they were submitted — re-sending base64
    blobs in subsequent turns bloats the context and causes Vertex AI to reject
    the request with 'Could not process image' (400 BadRequest). The model
    already processed the image in the original turn; the text response is what
    matters in history.
    """
    _IMAGE_TYPES = {"image", "document"}
    result = []
    for msg in messages:
        content = msg.get("content")
        if not isinstance(content, list):
            result.append(msg)
            continue
        kept = [
            b
            for b in content
            if not (isinstance(b, dict) and b.get("type") in _IMAGE_TYPES)
        ]
        if not kept:
            # All blocks were images — replace with a text placeholder so the
            # turn boundary is preserved (empty content is invalid for the API).
            kept = [{"type": "text", "text": "[image attached in original message]"}]
        result.append({**msg, "content": kept})
    return result


def _downgrade_thinking_blocks(messages: list[dict]) -> list[dict]:
    """Convert stored `thinking` blocks to plain `text` blocks, dropping their signature.

    Called once when a model switch is detected for a context. A thinking block's
    signature is only valid when replayed to the same model that generated it, so
    blocks from before the switch are flattened to text rather than risk an API
    rejection (or undocumented gateway behavior) on the next call to the new model.
    """
    result = []
    for msg in messages:
        content = msg.get("content")
        if not isinstance(content, list):
            result.append(msg)
            continue
        changed = False
        new_content = []
        for block in content:
            if isinstance(block, dict) and block.get("type") == "thinking":
                changed = True
                text = block.get("thinking", "")
                if text:
                    new_content.append({"type": "text", "text": text})
            else:
                new_content.append(block)
        if not changed:
            result.append(msg)
            continue
        result.append(
            {
                **msg,
                "content": new_content
                or [{"type": "text", "text": "[reasoning omitted]"}],
            }
        )
    return result


def _drop_orphaned_tool_use(messages: list[dict]) -> list[dict]:
    """Remove trailing assistant messages whose tool_use blocks have no paired tool_result.

    This guards against conversation corruption when a streaming failure leaves
    an agent turn with tool_use but no subsequent tool_result block.
    """
    if not messages:
        return messages
    # Collect all tool_use IDs and all tool_result IDs in the batch
    use_ids: set[str] = set()
    result_ids: set[str] = set()
    for msg in messages:
        content = msg.get("content", "")
        if not isinstance(content, list):
            continue
        for block in content:
            if block.get("type") == "tool_use":
                use_ids.add(block["id"])
            elif block.get("type") == "tool_result":
                result_ids.add(block.get("tool_use_id", ""))
    orphaned = use_ids - result_ids
    if not orphaned:
        return messages
    # Drop assistant messages that contain only orphaned tool_use blocks,
    # and inject a visible recovery message so the user knows the turn was interrupted.
    cleaned = []
    injected = False
    for msg in messages:
        content = msg.get("content", "")
        if isinstance(content, list) and msg.get("role") == "assistant":
            has_orphan = any(
                b.get("type") == "tool_use" and b.get("id") in orphaned for b in content
            )
            if has_orphan:
                print(
                    f"[conversation_store] dropping orphaned tool_use block(s): {orphaned}",
                    flush=True,
                )
                if not injected:
                    cleaned.append(
                        {
                            "role": "assistant",
                            "content": "⚠️ My previous response was interrupted before it could complete. Please resend your message and I'll try again.",
                        }
                    )
                    injected = True
                continue
        cleaned.append(msg)
    return cleaned


def _repair_tool_pairs(messages: list[dict]) -> list[dict]:
    """Return a copy of `messages` with every unpaired tool block removed.

    The Anthropic API requires each `tool_result` to sit immediately after an
    assistant message carrying the matching `tool_use`. A window sliced mid-pair,
    or a history interleaved by concurrent same-context requests, violates this and
    is rejected with "unexpected tool_use_id". We keep a tool_use/tool_result pair
    only when the assistant message is immediately followed by a user message that
    contains the matching result. All other tool blocks are dropped; text blocks are
    always kept, and any message left with empty content is removed.
    """
    if not messages:
        return messages

    def _ids(msg: dict, btype: str, key: str) -> set[str]:
        content = msg.get("content")
        if not isinstance(content, list):
            return set()
        out: set[str] = set()
        for block in content:
            if isinstance(block, dict) and block.get("type") == btype:
                val = block.get(key)
                if val:
                    out.add(val)
        return out

    valid: set[str] = set()
    for i in range(len(messages) - 1):
        a, b = messages[i], messages[i + 1]
        if a.get("role") == "assistant" and b.get("role") == "user":
            valid |= _ids(a, "tool_use", "id") & _ids(b, "tool_result", "tool_use_id")

    repaired: list[dict] = []
    for msg in messages:
        content = msg.get("content")
        if not isinstance(content, list):
            repaired.append(msg)
            continue
        kept = []
        for block in content:
            if isinstance(block, dict) and block.get("type") == "tool_use":
                if block.get("id") not in valid:
                    continue
            elif isinstance(block, dict) and block.get("type") == "tool_result":
                if block.get("tool_use_id") not in valid:
                    continue
            kept.append(block)
        if kept:
            repaired.append({**msg, "content": kept})
    return repaired


def _repair_openai_tool_pairs(messages: list[dict]) -> list[dict]:
    """Repair OpenAI-wire-format tool sequences.

    In OpenAI format an assistant tool call lives in a top-level ``tool_calls`` list
    and each result is a separate ``{"role": "tool", "tool_call_id": ...}`` message.
    The gateway rejects history where a ``role:"tool"`` message has no preceding
    assistant ``tool_calls`` declaring its id, or an assistant ``tool_calls`` entry
    was never answered. Anthropic-format messages pass through untouched.
    """
    if not messages:
        return messages

    declared: set[str] = set()
    answered: set[str] = set()
    for msg in messages:
        if msg.get("role") == "assistant" and isinstance(msg.get("tool_calls"), list):
            for tc in msg["tool_calls"]:
                tc_id = tc.get("id")
                if tc_id:
                    declared.add(tc_id)
        elif msg.get("role") == "tool":
            tc_id = msg.get("tool_call_id")
            if tc_id:
                answered.add(tc_id)

    if not declared and not answered:
        return messages  # no OpenAI-format tool messages at all

    valid = declared & answered
    if declared == answered:
        return messages  # everything pairs up — nothing to repair

    repaired: list[dict] = []
    for msg in messages:
        role = msg.get("role")
        if role == "tool":
            if msg.get("tool_call_id") in valid:
                repaired.append(msg)
            else:
                print(
                    f"[conversation_store] dropping orphaned tool message: {msg.get('tool_call_id')}",
                    flush=True,
                )
            continue
        if role == "assistant" and isinstance(msg.get("tool_calls"), list):
            kept_calls = [tc for tc in msg["tool_calls"] if tc.get("id") in valid]
            if kept_calls:
                repaired.append({**msg, "tool_calls": kept_calls})
            else:
                content = msg.get("content")
                if isinstance(content, str) and content.strip():
                    repaired.append({k: v for k, v in msg.items() if k != "tool_calls"})
                else:
                    print(
                        "[conversation_store] dropping unanswered assistant tool_calls turn",
                        flush=True,
                    )
            continue
        repaired.append(msg)
    return repaired


def _repair_all(messages: list[dict]) -> list[dict]:
    """Apply both Anthropic and OpenAI tool-pair repairs. Each is a no-op on the
    other provider's message format, so chaining them is safe regardless of which
    provider produced the history."""
    return _repair_openai_tool_pairs(_repair_tool_pairs(messages))


def _summarize_old_turns(turns: list[dict]) -> str:
    """Build a compact text summary of old turns without calling the LLM.

    Tool results are included as structured excerpts (first 300 chars).
    """
    parts = ["[CONVERSATION CONTEXT - earlier turns summarized to save tokens]\n"]
    for msg in turns:
        role = msg.get("role", "")
        content = msg.get("content", "")
        if isinstance(content, str):
            excerpt = content[:300] + ("..." if len(content) > 300 else "")
            parts.append(f"{role.upper()}: {excerpt}")
        elif isinstance(content, list):
            for block in content:
                btype = block.get("type", "")
                if btype == "text":
                    text = block.get("text", "")
                    parts.append(
                        f"{role.upper()}: {text[:300]}{'...' if len(text) > 300 else ''}"
                    )
                elif btype == "tool_result":
                    tool_content = block.get("content", "")
                    if isinstance(tool_content, str):
                        parts.append(
                            f"TOOL RESULT: {tool_content[:300]}{'...' if len(tool_content) > 300 else ''}"
                        )
                elif btype == "tool_use":
                    parts.append(
                        f"TOOL CALL: {block.get('name', '')}({block.get('input', {})})"
                    )
    parts.append("[END SUMMARY - recent conversation follows]")
    return "\n".join(parts)


async def _llm_summarize(turns: list[dict], provider, model: str) -> str:
    """Call the LLM to write a compact summary of old conversation turns.

    Falls back to the static `_summarize_old_turns` if the LLM call fails,
    so compaction never crashes the chat.
    """
    import logging

    _log = logging.getLogger(__name__)
    static_summary = _summarize_old_turns(turns)
    prompt = (
        "You are a conversation compactor. Below is a transcript of earlier turns "
        "in an ongoing conversation. Write a dense, factual summary (200–400 words) "
        "that preserves: every task the user asked for, every result or answer given, "
        "every file name / ID / URL / date mentioned, and any decisions made. "
        "Do NOT editorialize or add commentary. Output only the summary.\n\n"
        + static_summary
    )
    try:
        result_text = ""
        async for event in provider.stream_turn(
            model,
            "You are a helpful assistant.",
            [{"role": "user", "content": prompt}],
            [],
        ):
            if event["type"] == "text_delta":
                result_text += event["text"]
        summary = result_text.strip()
        if not summary:
            raise ValueError("empty LLM summary")
        return f"[CONVERSATION SUMMARY — earlier turns compacted]\n\n{summary}\n\n[END SUMMARY — recent conversation follows]"
    except Exception as exc:
        _log.warning(
            "[compact] LLM summarization failed (%s), using static fallback", exc
        )
        return static_summary
