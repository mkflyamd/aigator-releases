"""Skill Router — direct-dispatch for predictable queries.

Instead of paying ~4K tokens to ask the LLM "which tool should I call?",
the router pattern-matches the user's message and calls the tool function
directly. The LLM only sees the results — one call, zero tools sent.

Each skill can register DIRECT_INTENTS in its tools.py:

    DIRECT_INTENTS = [
        {
            "patterns": ["check my email", "inbox", "unread"],
            "tool": "read_email",
            "args": {"count": 10},
        },
    ]

The router auto-discovers these at startup alongside TOOL_DEFS/TOOL_HANDLERS.
"""

import logging
import re

_log = logging.getLogger(__name__)

# All registered intents (populated by register_intents / auto-discovery)
_INTENTS: list[dict] = []


def register_intents(skill_id: str, intents: list[dict]) -> None:
    """Register direct intents for a skill. Called during skill loading."""
    for intent in intents:
        _INTENTS.append({
            "skill": skill_id,
            "patterns": intent["patterns"],
            "tool": intent["tool"],
            "args": intent.get("args", {}),
        })
    _log.info("[skill-router] registered %d intents for %s", len(intents), skill_id)


def match_intent(message: str) -> dict | None:
    """Match a user message against registered direct intents.

    Returns the first matching intent dict, or None if no match.

    NOTE: The caller (routes/chat.py) is responsible for skipping the direct
    path when a non-builtin skill (MCP connection / installed skill) is in play
    for the turn — the direct router only covers built-in token-saving shortcuts.
    """
    msg_lower = message.lower().strip()
    if not msg_lower:
        return None
    for intent in _INTENTS:
        for pattern in intent["patterns"]:
            if pattern in msg_lower:
                _log.info("[skill-router] DIRECT match: '%s' -> %s(%s)",
                          pattern, intent["tool"], intent["args"])
                return intent
    return None


async def execute_direct(intent: dict, execute_tool_fn, user_message: str = "") -> dict:
    """Execute a matched intent by calling the tool function directly.

    Args:
        intent: matched intent dict
        execute_tool_fn: async tool executor
        user_message: the user's original message (passed as 'query' or 'task' for tools that need it)

    Returns the tool result dict.
    """
    tool_name = intent["tool"]
    args = dict(intent.get("args", {}))
    # For tools that need the user's message as input (e.g., browser_search needs 'query')
    if user_message and "query" not in args and "task" not in args:
        if tool_name.startswith("browser"):
            args["query"] = user_message
    _log.info("[skill-router] executing %s(%s)", tool_name, args)
    try:
        result = await execute_tool_fn(tool_name, args)
        return {"ok": True, "tool": tool_name, "skill": intent["skill"], "data": result}
    except Exception as exc:
        _log.warning("[skill-router] %s failed: %s", tool_name, exc)
        return {"ok": False, "tool": tool_name, "error": str(exc)}
