"""Model registry and provider lifecycle management."""
from __future__ import annotations
import logging
import threading
from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .base import LLMProvider

logger = logging.getLogger(__name__)


@dataclass
class ModelEntry:
    model_id: str
    provider: str
    context_window: int
    display_name: str
    supports_thinking: bool = False


# Runtime state — populated by load_profile()
_lock: threading.RLock = threading.RLock()
MODEL_REGISTRY: dict[str, ModelEntry] = {}
_active_model: str = ""
_active_profile: dict = {}
_provider_cache: dict[str, "LLMProvider"] = {}


def get_active_model() -> str:
    with _lock:
        return _active_model


def get_active_profile() -> dict:
    with _lock:
        return dict(_active_profile)


def set_active_model(model_id: str) -> None:
    global _active_model
    with _lock:
        if model_id not in MODEL_REGISTRY:
            raise ValueError(f"Unknown model: {model_id}. Available: {', '.join(MODEL_REGISTRY)}")
        _active_model = model_id


def available_models() -> list[str]:
    with _lock:
        return list(MODEL_REGISTRY.keys())


def context_window(model_id: str) -> int:
    with _lock:
        entry = MODEL_REGISTRY.get(model_id)
    return entry.context_window if entry else 200000


def model_supports_thinking(model_id: str) -> bool:
    with _lock:
        entry = MODEL_REGISTRY.get(model_id)
    return entry.supports_thinking if entry else False


def load_profile(profile: dict) -> None:
    """Switch the active LLM profile. Rebuilds MODEL_REGISTRY and evicts provider cache."""
    global _active_model, _active_profile
    with _lock:
        _active_profile = dict(profile)
        _provider_cache.clear()

        base_provider = "anthropic" if profile.get("type") == "anthropic" else "openai"
        anthropic_url = profile.get("anthropic_url", "")
        MODEL_REGISTRY.clear()
        for mid in profile.get("models", []):
            # Route Claude models through AnthropicProvider when anthropic_url is set
            if anthropic_url and mid.lower().startswith("claude"):
                prov = "anthropic"
            else:
                prov = base_provider
            MODEL_REGISTRY[mid] = ModelEntry(
                model_id=mid,
                provider=prov,
                context_window=200000,
                display_name=mid,
                supports_thinking=False,
            )

        active = profile.get("active_model", "")
        if active and active in MODEL_REGISTRY:
            _active_model = active
        elif MODEL_REGISTRY:
            _active_model = next(iter(MODEL_REGISTRY))
        else:
            _active_model = ""

        if active and active not in MODEL_REGISTRY and MODEL_REGISTRY:
            logger.warning("active_model %r not found in profile models; using %r", active, _active_model)


def get_provider(model_id: str | None = None) -> "LLMProvider":
    """Get the LLM provider for a model. Caches one singleton per provider name."""
    with _lock:
        mid = model_id or _active_model
        entry = MODEL_REGISTRY.get(mid)
        provider_name = entry.provider if entry else ("anthropic" if _active_profile.get("type") == "anthropic" else "openai")
        profile_snapshot = dict(_active_profile)

        if provider_name not in _provider_cache:
            if provider_name == "anthropic":
                from .anthropic_provider import AnthropicProvider
                _provider_cache[provider_name] = AnthropicProvider()
            else:
                from .openai_provider import OpenAIProvider
                _provider_cache[provider_name] = OpenAIProvider(profile_snapshot)

        return _provider_cache[provider_name]


def reset_provider(provider_name: str) -> None:
    """Evict cached provider singleton."""
    with _lock:
        _provider_cache.pop(provider_name, None)
