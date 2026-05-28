"""Multi-provider LLM abstraction layer for Gator Chat."""

from .base import LLMProvider, StreamEvent, ToolCall, TurnResult
from .gateway import (
    LLM_GATEWAY_URL,
    create_gateway_chat_anthropic,
    gateway_headers,
)
from .registry import (
    MODEL_REGISTRY,
    ModelEntry,
    available_models,
    context_window,
    get_active_model,
    get_active_profile,
    get_provider,
    load_profile,
    model_supports_thinking,
    reset_provider,
    set_active_model,
)

__all__ = [
    "LLM_GATEWAY_URL",
    "LLMProvider",
    "StreamEvent",
    "ToolCall",
    "TurnResult",
    "MODEL_REGISTRY",
    "ModelEntry",
    "available_models",
    "context_window",
    "create_gateway_chat_anthropic",
    "gateway_headers",
    "get_active_model",
    "get_active_profile",
    "get_provider",
    "load_profile",
    "model_supports_thinking",
    "reset_provider",
    "set_active_model",
]
