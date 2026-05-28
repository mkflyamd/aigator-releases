"""LLM-driven connection fixer — last-resort retry layer.

When deterministic connection logic in GenericMCPClient/StdioMCPClient
fails, this module asks an LLM to suggest a small URL or path tweak
that might work (e.g. trailing slash, /mcp suffix, /sse suffix,
versioned path). The suggestion is constrained to the same host as the
original URL — we never let the LLM redirect us to a different domain.

Skipped error classes:
- auth errors (401/403) — only the user can supply credentials
- DNS / connection refused / SSL — the URL is fundamentally wrong or
  the server doesn't exist; URL tweaks won't help
"""
from __future__ import annotations

import json
import logging
import urllib.parse
from typing import Callable

_log = logging.getLogger(__name__)

# Errors where retry with a different URL has no chance of helping
_UNRECOVERABLE_PATTERNS = (
    "auth_error:",
    "Could not resolve host",
    "Connection refused",
    "SSL error",
)

_MAX_LLM_ATTEMPTS = 2

_PROMPT = """You are debugging a Model Context Protocol (MCP) server connection.

The user pasted this as the server reference:
{raw_input}

We tried to connect to: {url}
The server responded with: {error}

We have already tried these URLs (all failed):
{previous}

Suggest ONE small URL modification that might work. Common fixes:
- Append /mcp or /sse to the path
- Add or remove a trailing slash
- Try a versioned path like /v1/mcp or /api/v1
- Try the parent path

Constraints:
- MUST keep the same scheme and host as the original URL
- Do NOT suggest a URL we already tried
- If nothing reasonable to try, say so

Respond with strict JSON only (no prose, no markdown fences):
{{"url": "https://same-host/different-path"}}
or
{{"skip": true, "reason": "short reason"}}
"""


def _llm_call(prompt: str) -> str:
    """Call the LLM using the same provider the user has configured in Gator."""
    from llm.anthropic_provider import AnthropicProvider
    provider = AnthropicProvider()
    return provider.simple_complete(prompt, max_tokens=256)


def is_recoverable(error: str) -> bool:
    """Return True if a URL tweak might help, False if the error is terminal."""
    return not any(p in error for p in _UNRECOVERABLE_PATTERNS)


def suggest_fix(
    url: str,
    error: str,
    raw_input: str,
    previous_urls: list[str],
    llm: Callable[[str], str] | None = None,
) -> str | None:
    """Ask the LLM for one URL variant to try next.

    Returns the suggested URL, or None if no suggestion is usable.
    Suggested URL is validated to have the same host as the original.
    """
    if not is_recoverable(error):
        _log.info("[fixer] error is unrecoverable, skipping: %s", error[:120])
        return None

    if len(previous_urls) >= _MAX_LLM_ATTEMPTS + 1:  # +1 for the original
        _log.info("[fixer] reached max attempts (%d), giving up", _MAX_LLM_ATTEMPTS)
        return None

    call = llm or _llm_call
    prev_block = "\n".join(f"  - {u}" for u in previous_urls) or "  (none)"
    prompt = _PROMPT.format(url=url, error=error[:300], raw_input=raw_input[:300], previous=prev_block)

    try:
        raw = call(prompt).strip()
        # Tolerate accidental markdown fencing
        if raw.startswith("```"):
            raw = raw.strip("`").lstrip("json").strip()
        data = json.loads(raw)
    except Exception as e:
        _log.info("[fixer] LLM call/parse failed: %s", e)
        return None

    if data.get("skip"):
        _log.info("[fixer] LLM skipped: %s", data.get("reason", ""))
        return None

    suggested = data.get("url", "").strip()
    if not suggested:
        return None

    # Security: enforce same-host policy
    orig = urllib.parse.urlparse(url)
    new = urllib.parse.urlparse(suggested)
    if new.netloc != orig.netloc or new.scheme != orig.scheme:
        _log.warning("[fixer] rejecting cross-host suggestion: %s → %s", url, suggested)
        return None

    if suggested in previous_urls:
        _log.info("[fixer] LLM suggested already-tried URL: %s", suggested)
        return None

    _log.info("[fixer] suggesting: %s → %s", url, suggested)
    return suggested
