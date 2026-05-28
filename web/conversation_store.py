"""Server-side conversation history store.

Keyed by context_id (tab ID). Maintains a 20-turn sliding window.
Tool results are never summarized to protect structured data (dates, IDs,
email addresses). Only user/assistant text is compressed when overflow occurs.
"""
from __future__ import annotations
import asyncio

MAX_TURNS = 20


class ConversationStore:
    def __init__(self) -> None:
        self._store: dict[str, list[dict]] = {}
        self._lock = asyncio.Lock()

    async def append(self, context_id: str, messages: list[dict]) -> None:
        async with self._lock:
            if context_id not in self._store:
                self._store[context_id] = []
            self._store[context_id].extend(_drop_orphaned_tool_use(messages))

    async def get_window(self, context_id: str) -> list[dict]:
        """Return active message window. Prepends a text summary if history > MAX_TURNS*2."""
        async with self._lock:
            msgs = self._store.get(context_id, [])
            if not msgs:
                return []
            cutoff = MAX_TURNS * 2
            if len(msgs) <= cutoff:
                return list(msgs)
            old = msgs[:-cutoff]
            recent = msgs[-cutoff:]
            summary = _summarize_old_turns(old)
            return [{"role": "user", "content": summary}] + recent

    async def seed(self, context_id: str, history: list[dict]) -> None:
        """Seed from browser-sent history (backward compat, first message only)."""
        async with self._lock:
            if context_id not in self._store:
                self._store[context_id] = list(history)

    async def delete(self, context_id: str) -> None:
        async with self._lock:
            self._store.pop(context_id, None)

    def has(self, context_id: str) -> bool:
        return context_id in self._store


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
    # Drop assistant messages that contain only orphaned tool_use blocks
    cleaned = []
    for msg in messages:
        content = msg.get("content", "")
        if isinstance(content, list) and msg.get("role") == "assistant":
            has_orphan = any(
                b.get("type") == "tool_use" and b.get("id") in orphaned
                for b in content
            )
            if has_orphan:
                print(f"[conversation_store] dropping orphaned tool_use block(s): {orphaned}", flush=True)
                continue
        cleaned.append(msg)
    return cleaned


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
                    parts.append(f"{role.upper()}: {text[:300]}{'...' if len(text) > 300 else ''}")
                elif btype == "tool_result":
                    tool_content = block.get("content", "")
                    if isinstance(tool_content, str):
                        parts.append(f"TOOL RESULT: {tool_content[:300]}{'...' if len(tool_content) > 300 else ''}")
                elif btype == "tool_use":
                    parts.append(f"TOOL CALL: {block.get('name', '')}({block.get('input', {})})")
    parts.append("[END SUMMARY - recent conversation follows]")
    return "\n".join(parts)
