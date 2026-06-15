"""Centralized LLM Gateway configuration.

ALL LLM client creation that goes through a gateway MUST use
``gateway_headers()`` or ``create_gateway_chat_anthropic()`` from this module.
Never construct gateway headers inline.

Configure via config.json (see docs/gateway-setup.md). At startup, app.py
reads config and sets the env vars this module reads.
"""

from __future__ import annotations

import os

# Backward-compatible constant — use get_gateway_url() for dynamic access.
# This reflects the value at import time; callers that need the live value
# should call get_gateway_url() instead.
LLM_GATEWAY_URL: str = "https://api.anthropic.com"


def get_gateway_url() -> str:
    """Return the configured gateway URL, reading from env on every call."""
    return os.environ.get("LLM_GATEWAY_URL", "https://api.anthropic.com")


def normalize_openai_base_url(raw: str) -> str:
    """Normalize a user-entered base URL to the correct OpenAI-wire base.

    The OpenAI SDK appends ``/chat/completions`` and ``/models`` itself, so the
    base must end at the version segment. Rules (on the trimmed, trailing-slash-
    stripped URL):

    - empty -> ""
    - contains ``/v1beta/openai`` (Gemini) -> as-is (Gemini has no ``/v1``)
    - already ends with ``/v1`` -> as-is
    - otherwise -> append ``/v1``

    Covers OpenAI (``api.openai.com`` -> ``+/v1``), Groq
    (``api.groq.com/openai`` -> ``/openai/v1``), LM Studio / Ollama
    (``host:port`` -> ``+/v1``), and Gemini (``.../v1beta/openai`` unchanged).
    """
    url = (raw or "").strip().rstrip("/")
    if not url:
        return ""
    if "/v1beta/openai" in url:
        return url
    if url.endswith("/v1"):
        return url
    return url + "/v1"


def gateway_headers(api_key: str | None = None) -> dict[str, str]:
    """Return configured gateway headers, or empty dict for direct Anthropic.

    Reads from env vars set at startup:
    - ``GATEWAY_KEY_HEADER`` — header name for the API key (e.g. ``Ocp-Apim-Subscription-Key``)
    - ``GATEWAY_USER_FIELD`` — header name for the user identifier (e.g. ``user``)
    - ``GATEWAY_USER_ID``   — the user identifier value
    """
    key_header = os.environ.get("GATEWAY_KEY_HEADER", "")
    user_field = os.environ.get("GATEWAY_USER_FIELD", "")
    user = os.environ.get("GATEWAY_USER_ID", "")

    headers: dict[str, str] = {}
    if key_header:
        key = api_key or os.environ.get("ANTHROPIC_API_KEY", "")
        if key:
            headers[key_header] = key
    if user_field and user:
        headers[user_field] = user
    return headers


def profile_headers(profile: dict) -> dict:
    """Build auth headers generically from a profile dict.

    Supports any provider type — reads api_key_header and user_id fields.
    Falls back to GATEWAY_USER_ID env var when user_id is absent so that
    the ``user`` header is always present (required for gateway compliance).
    """
    headers: dict[str, str] = {}
    key = profile.get("api_key", "")
    key_header = profile.get("api_key_header", "")
    user_id = profile.get("user_id", "") or os.environ.get("GATEWAY_USER_ID", "")
    if key_header and key:
        headers[key_header] = key
    if user_id:
        headers["user"] = user_id
    return headers


def is_gateway_url(url: str) -> bool:
    """Return True if *url* matches the configured gateway URL."""
    configured = get_gateway_url()
    if configured == "https://api.anthropic.com":
        return False
    return (url or "").startswith(configured)


def create_gateway_chat_anthropic(model: str, api_key: str, base_url: str = ""):
    """Create a ChatAnthropic instance pre-configured for the active gateway."""
    from browser_use.llm.anthropic.chat import ChatAnthropic

    url = base_url or f"{get_gateway_url()}/"

    # Prefer profile_headers (reads api_key_header from the active profile) so
    # that the correct subscription key header is sent even when the legacy
    # GATEWAY_KEY_HEADER env var is not set (profiles-only config).
    try:
        from .registry import get_active_profile
        _profile = get_active_profile()
        extra = profile_headers(_profile) if _profile else gateway_headers(api_key)
    except Exception:
        extra = gateway_headers(api_key)

    kwargs = {"model": model, "api_key": api_key, "base_url": url}
    if extra:
        kwargs["default_headers"] = extra
    return ChatAnthropic(**kwargs)


def create_gateway_chat_openai(model: str, api_key: str, base_url: str = ""):
    """Create a ChatOpenAI instance with gateway headers when routed through a gateway."""
    from browser_use.llm.openai.chat import ChatOpenAI

    kwargs = {"model": model, "api_key": api_key}
    if base_url:
        kwargs["base_url"] = base_url
        if is_gateway_url(base_url):
            try:
                from .registry import get_active_profile
                _profile = get_active_profile()
                extra = profile_headers(_profile) if _profile else gateway_headers(api_key)
            except Exception:
                extra = gateway_headers(api_key)
            if extra:
                kwargs["default_headers"] = extra
    return ChatOpenAI(**kwargs)
